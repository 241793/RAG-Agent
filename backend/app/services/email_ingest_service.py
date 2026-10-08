"""邮件入库服务：IMAP 拉取 → 正文/附件落库 → 走入库流水线。

安全：
- 只读拉取（BODY.PEEK / 不设 \\Seen），不删除、不移动用户邮件。
- 密码经 core.crypto 加密存储；连接失败写 last_error 不抛。
- 按邮件 UID 去重（seen_uids），避免重复入库。
"""
from __future__ import annotations

import email
import email.header
import imaplib
import time
from email.message import Message as EmailMessage

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

logger = get_logger("email_ingest")

# 可入库的附件扩展名（与 document.ALLOWED_EXT 保持一致）
INGESTABLE_EXT = {
    "pdf", "docx", "xlsx", "xls", "pptx", "md", "markdown",
    "html", "htm", "csv", "txt", "text", "log",
}
_MAX_UID_KEEP = 500  # 每源保留的已处理 UID 上限


def _safe_decode(payload: bytes, charset: str | None) -> str:
    """按声明字符集解码，失败则依次回退（邮件常见 chrome/unknown-8bit 等非标准名）。"""
    candidates = [charset, "utf-8", "gbk", "latin-1"]
    for enc in candidates:
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
        if isinstance(data, bytes):
            out.append(_safe_decode(data, enc))
        else:
            out.append(str(data))
    text = "".join(out)
    # 兜底：非标准客户端把 UTF-8 直接塞进头部（未按 RFC2047 编码），Python 按 latin-1 读成乱码。
    # 若还原后是合法 UTF-8 且含 CJK，则采用还原结果。
    if any("À" <= ch <= "ÿ" for ch in text):
        try:
            recovered = text.encode("latin-1").decode("utf-8")
            if any("一" <= ch <= "鿿" for ch in recovered):
                return recovered
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


def _fetch_messages(src) -> list[dict]:
    """同步拉取（在线程中执行）。返回 [{uid, subject, from, text, attachments:[{name,data}]}]。"""
    from app.core.crypto import decrypt

    pwd = decrypt(src.password) if src.password else ""
    if src.use_ssl:
        conn = imaplib.IMAP4_SSL(src.imap_host, src.imap_port)
    else:
        conn = imaplib.IMAP4(src.imap_host, src.imap_port)
    conn.login(src.username, pwd)
    out: list[dict] = []
    try:
        conn.select(src.folder, readonly=True)  # 只读，避免标记已读
        typ, data = conn.uid("search", None, "ALL")
        if typ != "OK":
            return []
        uids = data[0].split()[-30:]  # 只看最近 30 封，避免一次拉太多
        seen = set(str(u) for u in (src.seen_uids or []))
        for raw_uid in uids:
            uid = raw_uid.decode() if isinstance(raw_uid, bytes) else str(raw_uid)
            if uid in seen:
                continue
            typ, msg_data = conn.uid("fetch", raw_uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg: EmailMessage = email.message_from_bytes(msg_data[0][1])
            subject = _decode_header(msg.get("Subject"))
            sender = _decode_header(msg.get("From"))
            text = ""
            attachments: list[dict] = []
            for part in msg.walk():
                ctype = part.get_content_type()
                disp = str(part.get("Content-Disposition") or "")
                fname = _decode_header(part.get_filename())
                if fname or "attachment" in disp:
                    if fname:
                        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                        if ext in INGESTABLE_EXT:
                            payload = part.get_payload(decode=True)
                            if payload:
                                attachments.append({"name": fname, "data": payload})
                elif ctype == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        text += _safe_decode(payload, part.get_content_charset())
            out.append({"uid": uid, "subject": subject, "from": sender,
                        "text": text, "attachments": attachments})
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        conn.logout()
    return out


def _matches(src, msg: dict) -> bool:
    """按发件人/主题关键词过滤。"""
    allow = [x.strip().lower() for x in (src.allow_from or "").split(",") if x.strip()]
    if allow and not any(a in (msg.get("from") or "").lower() for a in allow):
        return False
    kws = [x.strip() for x in (src.subject_keywords or "").split(",") if x.strip()]
    if kws and not any(k in (msg.get("subject") or "") for k in kws):
        return False
    return True


async def _ingest_one(db: AsyncSession, src, msg: dict) -> int:
    """把一封邮件（正文 + 附件）入库。返回新增文档数。"""
    from app.ingest.storage import get_storage
    from app.models import Document
    from app.tasks.ingest_tasks import enqueue_document

    storage = get_storage()
    created = 0
    subject = msg.get("subject") or f"邮件 {msg.get('uid')}"
    sender = msg.get("from") or ""

    docs: list[tuple[str, bytes]] = []
    if src.ingest_mode in ("both", "body") and msg.get("text"):
        body_name = f"{subject[:60]}.txt"
        docs.append((body_name, msg["text"].encode("utf-8")))
    if src.ingest_mode in ("both", "attach"):
        for att in msg.get("attachments") or []:
            docs.append((att["name"], att["data"]))

    for filename, data in docs:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
        if ext not in INGESTABLE_EXT:
            continue
        file_key, chash = storage.save(tenant_id=src.tenant_id, filename=filename, data=data)
        dup = (await db.execute(
            select(Document).where(Document.kb_id == src.kb_id, Document.content_hash == chash)
        )).scalar_one_or_none()
        if dup:
            try:
                storage.delete(file_key)
            except Exception:  # noqa: BLE001
                pass
            continue
        doc = Document(
            tenant_id=src.tenant_id, kb_id=src.kb_id,
            title=f"[邮件] {filename}" if ext == "txt" else filename,
            source_type="email", source_uri=sender[:512],
            file_key=file_key, file_name=filename, file_ext=ext,
            file_size=len(data), content_hash=chash, status="pending",
            uploaded_by=src.uploaded_by, metadata_={"email_subject": subject, "email_from": sender},
        )
        db.add(doc)
        await db.flush()
        await enqueue_document(doc.id)
        created += 1
    return created


async def sync_source(db: AsyncSession, src) -> dict:
    """拉取一个邮件源的新邮件并入库。返回统计。"""
    import asyncio

    if not src.enabled:
        return {"ok": False, "message": "该邮件源已禁用"}
    try:
        messages = await asyncio.wait_for(asyncio.to_thread(_fetch_messages, src), timeout=60)
    except Exception as e:  # noqa: BLE001
        src.status = "error"
        src.last_error = str(e)[:500]
        await db.flush()
        logger.warning("email_fetch_failed", source_id=src.id, err=str(e)[:200])
        return {"ok": False, "message": f"拉取失败：{str(e)[:200]}"}

    seen = list(src.seen_uids or [])
    total = 0
    for msg in messages:
        if not _matches(src, msg):
            seen.append(msg["uid"])
            continue
        try:
            total += await _ingest_one(db, src, msg)
        except Exception:  # noqa: BLE001
            logger.exception("email_ingest_one_failed", uid=msg.get("uid"))
        seen.append(msg["uid"])
    src.seen_uids = seen[-_MAX_UID_KEEP:]
    src.last_sync_at = int(time.time() * 1000)
    src.ingested_count = (src.ingested_count or 0) + total
    src.status = "active"
    src.last_error = None
    await db.flush()
    return {"ok": True, "message": f"拉取 {len(messages)} 封，新增入库 {total} 篇", "ingested": total}


async def test_source(src) -> dict:
    """测试连接（登录 + 选文件夹）。"""
    import asyncio

    from app.core.crypto import decrypt

    def _test() -> str:
        pwd = decrypt(src.password) if src.password else ""
        if src.use_ssl:
            conn = imaplib.IMAP4_SSL(src.imap_host, src.imap_port)
        else:
            conn = imaplib.IMAP4(src.imap_host, src.imap_port)
        try:
            conn.login(src.username, pwd)
            typ, data = conn.select(src.folder, readonly=True)
            if typ != "OK":
                raise ValueError(f"无法打开文件夹 {src.folder}")
            count = int(data[0]) if data and data[0] else 0
            return f"连接成功，文件夹「{src.folder}」有 {count} 封邮件"
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass

    try:
        msg = await asyncio.wait_for(asyncio.to_thread(_test), timeout=30)
        return {"ok": True, "message": msg}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)[:300]}
