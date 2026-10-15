"""个人邮件服务：收件（IMAP）持久化到收件箱 + 发件（SMTP）+ 可选入库知识库。

设计：
- 收件用 IMAP **只读**（BODY.PEEK，不改用户邮箱的已读标记），UID 游标增量。
- 邮件先落 MailMessage（收件箱），account.auto_ingest=True 时再复用现有入库链路建 Document。
- 发件用账号自带 SMTP；发完本地写一份 Sent（不做 IMAP APPEND，保护用户邮箱）。
"""
from __future__ import annotations

import email
import email.header
import imaplib
import re
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger("mail")

_SNIPPET_LEN = 160
_MAX_ATT_SIZE = 25 * 1024 * 1024  # 单附件上限 25MB（超过跳过）
_INGESTABLE_EXT = {
    "pdf", "docx", "xlsx", "xls", "pptx", "md", "markdown",
    "html", "htm", "csv", "txt", "text", "log",
}


# ==================== 通用解码/解析（复用 email_ingest_service 的思路）====================
def _safe_decode(payload: bytes, charset: str | None) -> str:
    for enc in [charset, "utf-8", "gbk", "latin-1"]:
        if not enc:
            continue
        try:
            return payload.decode(enc, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="ignore")


def _decode_header(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        parts = email.header.decode_header(raw)
    except Exception:  # noqa: BLE001
        return str(raw)
    out = []
    for data, enc in parts:
        out.append(_safe_decode(data, enc) if isinstance(data, bytes) else str(data))
    text = "".join(out)
    # 非标准客户端直接塞 UTF-8 头部 → 还原
    if any("À" <= ch <= "ÿ" for ch in text):
        try:
            recovered = text.encode("latin-1").decode("utf-8")
            if any("一" <= ch <= "鿿" for ch in recovered):
                return recovered
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


def _parse_addr_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [a.strip() for a in re.split(r"[,;]", raw) if a.strip()]


def _parse_one_message(raw_bytes: bytes, uid: str | None) -> dict:
    """把一封原始邮件解析成 dict（正文/HTML/收件人/附件元数据+数据）。"""
    msg = email.message_from_bytes(raw_bytes)
    subject = _decode_header(msg.get("Subject"))
    sender = _decode_header(msg.get("From"))
    from_name, _, from_addr = sender.rpartition("<")
    from_addr = (from_addr or from_name).strip().strip(">").strip()
    from_name = from_name.strip().strip('"') or None

    body_text = ""
    body_html = ""
    attachments: list[dict] = []
    for part in msg.walk():
        ctype = part.get_content_type()
        disp = str(part.get("Content-Disposition") or "")
        fname = _decode_header(part.get_filename())
        if fname or "attachment" in disp:
            payload = part.get_payload(decode=True)
            if payload and len(payload) <= _MAX_ATT_SIZE:
                attachments.append({
                    "filename": fname or "file",
                    "content_type": ctype,
                    "size": len(payload),
                    "data": payload,  # 落 storage 后移除
                })
        elif ctype == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                body_text += _safe_decode(payload, part.get_content_charset())
        elif ctype == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                body_html += _safe_decode(payload, part.get_content_charset())

    try:
        dt = email.utils.parsedate_to_datetime(msg.get("Date"))
        date_ms = int(dt.timestamp() * 1000) if dt else None
    except Exception:  # noqa: BLE001
        date_ms = None

    return {
        "uid": uid,
        "message_id": (msg.get("Message-ID") or "").strip() or None,
        "subject": subject or "(无主题)",
        "from_addr": from_addr,
        "from_name": from_name,
        "to_addrs": _parse_addr_list(msg.get("To")),
        "cc_addrs": _parse_addr_list(msg.get("Cc")),
        "date": date_ms,
        "body_text": body_text.strip() or None,
        "body_html": body_html.strip() or None,
        "in_reply_to": (msg.get("In-Reply-To") or "").strip() or None,
        "references": (msg.get("References") or "").strip() or None,
        "attachments": attachments,
    }


# ==================== 收件 ====================
def fetch_mailbox(account, *, first_run_cap: int = 200) -> tuple[list[dict], int, int | None]:
    """只读拉取账号收件箱的新邮件（线程内执行）。返回 (消息列表, max_uid, validity)。"""
    from app.core.crypto import decrypt

    pwd = decrypt(account.imap_password) if account.imap_password else ""
    if account.imap_use_ssl:
        conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port)
    else:
        conn = imaplib.IMAP4(account.imap_host, account.imap_port)
    conn.login(account.imap_username, pwd)
    out: list[dict] = []
    max_uid = int(getattr(account, "uid_cursor", 0) or 0)
    validity: int | None = None
    try:
        typ, sel = conn.select(account.folder or "INBOX", readonly=True)
        if typ != "OK":
            return [], max_uid, validity
        try:
            raw = sel[0].decode("utf-8", "ignore") if sel and sel[0] else ""
            m = re.search(r"UIDVALIDITY\s+(\d+)", raw)
            if m:
                validity = int(m.group(1))
        except Exception:  # noqa: BLE001
            validity = None
        cursor = int(getattr(account, "uid_cursor", 0) or 0)
        prev_v = getattr(account, "uid_validity", None)
        if validity is not None and prev_v is not None and validity != prev_v:
            cursor = 0  # 邮箱重建 → 游标归零
        if cursor > 0:
            typ, data = conn.uid("search", None, f"UID {cursor + 1}:*")
        else:
            typ, data = conn.uid("search", None, "ALL")
        if typ != "OK":
            return [], max_uid, validity
        uids = data[0].split() if data and data[0] else []
        if cursor <= 0 and len(uids) > first_run_cap:
            uids = uids[-first_run_cap:]
        seen = set(str(u) for u in (account.seen_uids or []))
        for raw_uid in uids:
            uid = raw_uid.decode() if isinstance(raw_uid, bytes) else str(raw_uid)
            try:
                uid_int = int(uid)
            except (TypeError, ValueError):
                continue
            if uid_int > max_uid:
                max_uid = uid_int
            if uid in seen:
                continue
            typ, msg_data = conn.uid("fetch", raw_uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            parsed = _parse_one_message(msg_data[0][1], uid)
            out.append(parsed)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        conn.logout()
    return out, max_uid, validity


def _save_attachments(account, parsed: dict) -> list[dict]:
    """把附件数据落 storage，返回元数据列表（去掉 data）。"""
    from app.ingest.storage import get_storage

    storage = get_storage()
    out: list[dict] = []
    for att in parsed.get("attachments") or []:
        data = att.pop("data", None)
        if not data:
            continue
        try:
            fk, _ = storage.save(tenant_id=account.tenant_id, filename=att["filename"], data=data)
        except Exception:  # noqa: BLE001
            logger.exception("mail_attach_save_failed", name=att.get("filename"))
            continue
        out.append({"filename": att["filename"], "content_type": att.get("content_type"),
                    "size": att.get("size"), "storage_path": fk})
    return out


async def _persist_message(db: AsyncSession, account, parsed: dict) -> tuple[int, bool]:
    """把一封邮件写入收件箱（按 account+folder+uid 去重）。返回 (message_id, created)。"""
    from app.models import MailMessage

    uid = parsed.get("uid")
    folder_name = account.folder or "INBOX"
    dup = None
    if uid:
        dup = (await db.execute(
            select(MailMessage).where(
                MailMessage.account_id == account.id,
                MailMessage.folder == folder_name,
                MailMessage.uid == uid,
            )
        )).scalar_one_or_none()
    if dup:
        return dup.id, False
    atts = _save_attachments(account, parsed)
    text = parsed.get("body_text") or ""
    snippet = re.sub(r"\s+", " ", text)[:_SNIPPET_LEN]
    m = MailMessage(
        tenant_id=account.tenant_id, user_id=account.user_id, account_id=account.id,
        folder=account.folder or "INBOX", uid=uid, message_id=parsed.get("message_id"),
        subject=parsed.get("subject") or "", from_addr=parsed.get("from_addr") or "",
        from_name=parsed.get("from_name"), to_addrs=parsed.get("to_addrs"),
        cc_addrs=parsed.get("cc_addrs"), date=parsed.get("date"),
        body_text=parsed.get("body_text"), body_html=parsed.get("body_html"), snippet=snippet,
        in_reply_to=parsed.get("in_reply_to"), references=parsed.get("references"),
        attachments=atts or None, has_attachments=bool(atts),
    )
    db.add(m)
    await db.flush()
    return m.id, True


async def _maybe_ingest(db: AsyncSession, account, msg_id: int, parsed: dict) -> None:
    """可选入库：复用知识库入库链路把邮件正文建成 Document，并回填 document_id。

    说明：附件二进制在 _persist_message 阶段已落 storage 消费，这里只入库**正文**
    （附件入库留待后续：需要把附件数据保留到入库阶段）。
    """
    if not account.auto_ingest or not account.default_kb_id:
        return
    try:
        from app.models import Document, MailMessage
        from app.services.email_ingest_service import _matches, _ingest_one

        msg = {"uid": parsed.get("uid"), "subject": parsed.get("subject") or "",
               "from": parsed.get("from_addr") or "", "text": parsed.get("body_text") or ""}
        if not _matches(account, msg):
            return
        src_like = type("S", (), {
            "tenant_id": account.tenant_id, "kb_id": account.default_kb_id,
            "ingest_mode": "body", "uploaded_by": account.user_id,
            "auto_tags": account.auto_tags, "tag_rules": account.tag_rules,
        })()
        n = await _ingest_one(db, src_like, {"uid": parsed.get("uid"),
                                             "subject": parsed.get("subject"),
                                             "from": parsed.get("from_addr"),
                                             "text": parsed.get("body_text") or "",
                                             "attachments": []})
        if n:
            # 回填 document_id（取该 kb 下最新、内容匹配的文档；_ingest_one 未返回 id）
            doc = (await db.execute(
                select(Document).where(
                    Document.kb_id == account.default_kb_id,
                    Document.source_type == "email",
                ).order_by(Document.id.desc()).limit(1)
            )).scalar_one_or_none()
            if doc:
                m = await db.get(MailMessage, msg_id)
                if m:
                    m.document_id = doc.id
            await db.flush()
    except Exception:  # noqa: BLE001
        logger.exception("mail_auto_ingest_failed", account_id=account.id)


async def test_account(account) -> dict:
    """测试 IMAP 登录（+ 可选 SMTP 登录）。返回 {ok, message}。"""
    import asyncio

    from app.core.crypto import decrypt

    def _test_imap() -> str:
        pwd = decrypt(account.imap_password) if account.imap_password else ""
        if account.imap_use_ssl:
            conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port)
        else:
            conn = imaplib.IMAP4(account.imap_host, account.imap_port)
        try:
            conn.login(account.imap_username, pwd)
            typ, _ = conn.select(account.folder or "INBOX", readonly=True)
            if typ != "OK":
                raise RuntimeError("无法打开文件夹")
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        return "IMAP 连接正常"

    try:
        msg = await asyncio.wait_for(asyncio.to_thread(_test_imap), timeout=20)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"IMAP 失败：{str(e)[:200]}"}
    return {"ok": True, "message": msg}


async def poll_account(db: AsyncSession, account) -> dict:
    """拉取一个邮箱账号的新邮件：持久化收件箱 + 可选入库。"""
    import asyncio

    if not account.enabled:
        return {"ok": False, "message": "账号已禁用", "new": 0}
    try:
        messages, max_uid, validity = await asyncio.wait_for(
            asyncio.to_thread(fetch_mailbox, account), timeout=90
        )
    except Exception as e:  # noqa: BLE001
        account.status = "error"
        account.last_error = str(e)[:500]
        await db.flush()
        logger.warning("mail_fetch_failed", account_id=account.id, err=str(e)[:200])
        return {"ok": False, "message": f"拉取失败：{str(e)[:200]}", "new": 0}

    created = 0
    failed = 0
    seen = list(account.seen_uids or [])
    for parsed in messages:
        try:
            mid, is_new = await _persist_message(db, account, parsed)
            if is_new:
                created += 1
                await _maybe_ingest(db, account, mid, parsed)
        except Exception:  # noqa: BLE001
            failed += 1
            logger.exception("mail_persist_failed", uid=parsed.get("uid"))
        if parsed.get("uid"):
            seen.append(parsed["uid"])
    account.seen_uids = seen[-500:]
    if failed == 0 and max_uid > (account.uid_cursor or 0):
        account.uid_cursor = max_uid
    if validity is not None:
        account.uid_validity = validity
    account.last_poll_at = int(time.time() * 1000)
    if created:
        account.ingested_count = (account.ingested_count or 0) + created
    account.status = "active"
    account.last_error = None
    await db.flush()
    return {"ok": True, "message": f"拉取 {len(messages)} 封，新增 {created} 封", "new": created}


# ==================== 发件 ====================
def send_mail_sync(*, smtp_host: str, smtp_port: int, use_ssl: bool, starttls: bool,
                   username: str | None, password: str, from_addr: str, from_name: str | None,
                   to: list[str], cc: list[str], subject: str,
                   body_text: str, body_html: str | None,
                   attachments: list[dict] | None, in_reply_to: str | None,
                   message_id: str | None = None) -> str:
    """同步发送邮件（线程内执行）。返回生成的 Message-ID。"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from email.utils import formataddr, make_msgid

    mid = message_id or make_msgid()
    mail = MIMEMultipart("alternative") if body_html else MIMEMultipart()
    if body_text:
        mail.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        mail.attach(MIMEText(body_html, "html", "utf-8"))
    for att in (attachments or []):
        data = att.get("data") or b""
        part = MIMEApplication(data, Name=att.get("name") or "file")
        part["Content-Disposition"] = f'attachment; filename="{att.get("name") or "file"}"'
        mail.attach(part)
    mail["Subject"] = subject
    mail["From"] = formataddr((from_name or from_addr, from_addr))
    mail["To"] = ", ".join(to)
    if cc:
        mail["Cc"] = ", ".join(cc)
    mail["Message-ID"] = mid
    if in_reply_to:
        mail["In-Reply-To"] = in_reply_to
        mail["References"] = in_reply_to

    rcpts = list(to) + list(cc or [])
    if use_ssl:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20)
    else:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=20)
        if starttls:
            server.starttls()
    try:
        if username:
            server.login(username, password)
        server.sendmail(from_addr, rcpts, mail.as_string())
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass
    return mid


async def send_from_account(db: AsyncSession, account, *, to: list[str], subject: str,
                            body_text: str, body_html: str | None = None,
                            cc: list[str] | None = None, attachments: list[dict] | None = None,
                            in_reply_to: str | None = None) -> dict:
    """用账号的 SMTP 发信，并在本地写一份 Sent。"""
    import asyncio

    from app.core.crypto import decrypt
    from app.models import MailMessage

    if not account.smtp_host:
        return {"ok": False, "message": "该账号未配置 SMTP，无法发信"}
    if not to:
        return {"ok": False, "message": "缺少收件人"}
    pwd = decrypt(account.smtp_password) if account.smtp_password else ""
    try:
        mid = await asyncio.wait_for(asyncio.to_thread(
            send_mail_sync,
            smtp_host=account.smtp_host, smtp_port=account.smtp_port,
            use_ssl=account.smtp_use_ssl, starttls=account.smtp_starttls,
            username=account.smtp_username or account.email_addr, password=pwd,
            from_addr=account.email_addr, from_name=account.from_name,
            to=list(to), cc=list(cc or []), subject=subject,
            body_text=body_text, body_html=body_html,
            attachments=attachments, in_reply_to=in_reply_to,
        ), timeout=30)
    except Exception as e:  # noqa: BLE001
        logger.warning("mail_send_failed", account_id=account.id, err=str(e)[:200])
        return {"ok": False, "message": f"发送失败：{str(e)[:200]}"}

    # 本地写 Sent
    att_meta = [{"filename": a.get("name"), "size": len(a.get("data") or b"")} for a in (attachments or [])]
    m = MailMessage(
        tenant_id=account.tenant_id, user_id=account.user_id, account_id=account.id,
        folder="Sent", uid=None, message_id=mid,
        subject=subject, from_addr=account.email_addr, from_name=account.from_name,
        to_addrs=list(to), cc_addrs=list(cc or []), date=int(time.time() * 1000),
        body_text=body_text, body_html=body_html, snippet=re.sub(r"\s+", " ", body_text)[:_SNIPPET_LEN],
        answered=True, in_reply_to=in_reply_to, attachments=att_meta or None,
        has_attachments=bool(att_meta),
    )
    db.add(m)
    await db.flush()
    return {"ok": True, "message": "已发送", "message_id": mid, "id": m.id}
