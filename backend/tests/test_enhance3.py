"""第十三轮增强的回归：KB 级向量模型分组、文件夹重命名/排序、版本历史、外部同步、备份。

用静态/单元级校验（不依赖真实 embedding 上游），保证契约稳定。
"""
from __future__ import annotations

import asyncio
import inspect


# ==================== KB 级向量模型分组 ====================
def test_group_kbs_by_embedding_model_exists():
    from app.services import retrieval_service as R

    assert hasattr(R, "group_kbs_by_embedding_model")
    src = inspect.getsource(R.group_kbs_by_embedding_model)
    # 图文库（entry）应被单独摘出，不参与向量召回
    assert "entry" in src and "skip" in src


def test_search_vectors_by_model_groups():
    """多模型时按组分别生成 query 向量，并过滤掉非本组的 kb。"""
    from app.services import retrieval_service as R

    src = inspect.getsource(R._search_vectors_by_model)
    assert "config_id=model_id" in src
    assert "h.kb_id in set(kbs)" in src


def test_retrieve_uses_model_groups_not_plain_embed():
    from app.services import retrieval_service as R

    src = inspect.getsource(R.retrieve)
    assert "group_kbs_by_embedding_model" in src
    assert "_search_vectors_by_model" in src


def test_embed_query_accepts_config_id():
    from app.services.retrieval_service import embed_query

    sig = inspect.signature(embed_query)
    assert "config_id" in sig.parameters


def test_get_embedding_falls_back_to_default():
    """KB 指定模型失效时应回退租户默认，而非整体报错。"""
    from app.providers import registry

    src = inspect.getsource(registry.get_embedding)
    assert "if not models and config_id" in src


def test_ingest_uses_kb_embedding_model():
    from app.tasks import ingest_tasks

    src = inspect.getsource(ingest_tasks)
    assert "kb_model_id" in src and "config_id=kb_model_id" in src


def test_reembed_chunk_uses_kb_model():
    from app.api.v1.document import _reembed_chunk

    src = inspect.getsource(_reembed_chunk)
    assert "embedding_model_id" in src and "config_id=kb_model_id" in src


# ==================== 文件夹重命名 / 排序 ====================
def test_folder_update_endpoint_exists():
    from app.api.v1 import document as D

    methods = {(r.path, m) for r in D.router.routes for m in getattr(r, "methods", set())}
    assert ("/documents/folders/{folder_id}", "PATCH") in methods, "文件夹应有 PATCH 重命名/排序"
    assert ("/documents/folders/order", "PUT") in methods, "应有批量排序端点"


def test_folder_patch_prevents_cycle():
    from app.api.v1 import document as D

    src = inspect.getsource(D.update_folder)
    # 防环：移动到自身或子孙应被拒绝
    assert "移动到自身" in src or "移动到自己的子文件夹" in src


def test_create_folder_accepts_sort():
    from app.api.v1 import document as D

    assert "sort" in D.FolderIn.model_fields
    assert "sort" in D.FolderPatchIn.model_fields


# ==================== 文档版本历史 ====================
def test_document_version_model():
    from app.models import DocumentVersion

    assert hasattr(DocumentVersion, "__tablename__")
    cols = set(DocumentVersion.__table__.columns.keys())
    assert {"doc_id", "version", "content", "chunk_snapshot", "reason"} <= cols


def test_version_endpoints_registered():
    from app.api.v1 import document as D

    methods = {(r.path, m) for r in D.router.routes for m in getattr(r, "methods", set())}
    assert ("/documents/{doc_id}/versions", "GET") in methods
    assert ("/documents/{doc_id}/versions/{version}", "GET") in methods
    assert ("/documents/{doc_id}/versions/{version}/rollback", "POST") in methods


def test_archive_on_reprocess():
    from app.tasks import ingest_tasks

    src = inspect.getsource(ingest_tasks.process_document)
    assert "_archive_version" in src, "入库前应归档旧版本"


def test_archive_skips_first_version():
    from app.tasks.ingest_tasks import _archive_version

    src = inspect.getsource(_archive_version)
    # 首次入库（无旧分块）应返回 False，不产生版本记录
    assert "return False" in src


def test_snapshot_has_parent_ordinal():
    """快照需含 parent_ordinal，回滚才能重建父子关系。"""
    from app.tasks.ingest_tasks import _archive_version

    src = inspect.getsource(_archive_version)
    assert "parent_ordinal" in src


# ==================== 外部 KB 导入同步 ====================
def test_sync_service_exists():
    from app.services import kb_sync_service as S

    assert hasattr(S, "sync_external_kb")


def test_sync_endpoint_registered():
    from app.api.v1 import kb as K

    methods = {(r.path, m) for r in K.router.routes for m in getattr(r, "methods", set())}
    assert ("/kbs/{kb_id}/sync", "POST") in methods, "外部库应有手动同步端点"
    assert ("/kbs/{kb_id}/sync/status", "GET") in methods


def test_sync_only_for_external():
    from app.services.kb_sync_service import sync_external_kb

    src = inspect.getsource(sync_external_kb)
    assert "external" in src, "同步应校验库类型为 external"


# ==================== 备份 ====================
def test_backup_endpoints_exist():
    from app.api.v1 import system_ops as S

    methods = {(r.path, m) for r in S.router.routes for m in getattr(r, "methods", set())}
    paths = [p for p, _ in methods if "backup" in p]
    assert paths, "应存在备份相关端点"



# ==================== 存量 NULL 列兜底（本轮 500 修复）====================
def test_document_out_tolerates_null_columns():
    """存量行 kind/status/visibility 为 NULL 时，DocumentOut 应兜底而非 500。"""
    from app.schemas.kb import DocumentOut

    d = DocumentOut.model_validate({
        "id": 1, "kb_id": 1, "title": "t", "kind": None, "file_size": 0,
        "status": None, "visibility": None, "progress": 0,
        "page_count": 0, "char_count": 0, "chunk_count": 0,
        "created_at": "2026-01-01T00:00:00Z",
    })
    assert d.kind == "file"
    assert d.status == "pending"
    assert d.visibility == "inherit"


def test_scalar_default_helper():
    from app.core.db import _scalar_default
    from app.models import Document

    col = Document.__table__.c.kind
    assert _scalar_default(col) == "'file'"
    # 可空无默认列返回 None（不误改）
    assert _scalar_default(Document.__table__.c.content) is None


# ==================== 第①轮：假开关生效 + BM25 缓存 ====================
def test_retrieve_reads_settings_defaults():
    """retrieve 的 top_k/candidate_k 默认应取系统设置，而非硬编码。"""
    import inspect

    from app.services.retrieval_service import retrieve

    src = inspect.getsource(retrieve)
    assert "settings.retrieval_top_k" in src
    assert "settings.retrieval_candidate_k" in src
    sig = inspect.signature(retrieve)
    assert sig.parameters["top_k"].default is None
    assert sig.parameters["candidate_k"].default is None


def test_chat_request_top_k_optional():
    """ChatRequest.top_k 应为可选，未传时由后端用设置值。"""
    from app.schemas.chat import ChatRequest

    assert ChatRequest.model_fields["top_k"].default is None


def test_chat_request_kb_ids_three_state():
    """kb_ids 三态语义：None=沿用 / []=全库 / [id]=限定。"""
    from app.schemas.chat import ChatRequest

    assert ChatRequest.model_fields["kb_ids"].default is None


def test_get_or_create_keeps_binding_when_none():
    """未传 kb_ids（None）时应保留会话原有绑定，不再静默清空。"""
    import inspect

    from app.services.chat_service import get_or_create_conversation

    src = inspect.getsource(get_or_create_conversation)
    assert "if kb_ids is not None:" in src, "只有显式给出 kb_ids 才更新绑定"


def test_bm25_cache_key_includes_principals():
    """缓存键必须含 principals，否则不同权限主体会串缓存。"""
    import inspect

    from app.retrieval import bm25_cache

    src = inspect.getsource(bm25_cache.make_key)
    assert "principals" in src
    # 相同 kb 但不同主体 → 不同键
    k1 = bm25_cache.make_key(1, [1, 2], False, [100])
    k2 = bm25_cache.make_key(1, [1, 2], False, [200])
    assert k1 != k2


def test_bm25_cache_put_is_wired():
    """put 必须真被调用（此前是死代码）。"""
    import inspect

    from app.services.retrieval_service import retrieve

    src = inspect.getsource(retrieve)
    assert "bm25_cache.put" in src, "search 路径应写入 BM25 缓存"
    assert "on_build" in src


def test_bm25_keyword_search_has_on_build():
    import inspect

    from app.retrieval.bm25 import keyword_search

    assert "on_build" in inspect.signature(keyword_search).parameters


# ==================== 第③轮：AI 正确性 ====================
def test_workflow_retrieval_wraps_untrusted():
    """工作流检索节点应给内容加注入边界标记。"""
    import inspect

    from app.agents.workflow.engine import _exec_retrieval

    src = inspect.getsource(_exec_retrieval)
    assert "wrap_untrusted" in src, "工作流检索结果应加边界标记"


def test_workflow_llm_has_fallback_system():
    """工作流 LLM 节点无配置时应用引用规约兜底，而非空系统提示。"""
    import inspect

    from app.agents.workflow import engine

    assert hasattr(engine, "_LLM_FALLBACK_SYSTEM")
    src = inspect.getsource(engine._exec_llm)
    assert "_LLM_FALLBACK_SYSTEM" in src


def test_agent_runner_restores_mode_on_resume():
    """HITL 续跑应按 action 里记录的 mode_id 还原行为模式。"""
    import inspect

    from app.agents.runner import AgentRunner

    src = inspect.getsource(AgentRunner.resume_action)
    assert 'raw.get("mode_id")' in src
    assert "build_effective(self.db, self.agent, mode)" in src


def test_agent_pending_action_records_mode():
    import inspect

    from app.agents.runner import AgentRunner

    src = inspect.getsource(AgentRunner._create_pending_action)
    assert "mode_id" in src, "待确认动作应记录 mode_id 供续跑还原"


def test_agent_has_citation_rule():
    """智能体应注入引用纪律，与问答页对齐。"""
    import inspect

    from app.agents import runner

    assert hasattr(runner, "_CITATION_RULE")
    assert "_CITATION_RULE" in inspect.getsource(runner.AgentRunner.run)
    assert "_CITATION_RULE" in inspect.getsource(runner.AgentRunner.resume_action)


def test_agent_runs_citation_check():
    """智能体结束时应做引用真实性校验（与问答页一致）。"""
    import inspect

    from app.agents.runner import AgentRunner

    src = inspect.getsource(AgentRunner.run)
    assert "citation_check" in src


# ==================== 第④轮：引用定位 + 交互 ====================
def test_permission_decode_principals():
    """principal 编解码与名称解析。"""
    from app.services.permission import (
        PUBLIC, decode_principal, dept_principal, group_principal,
        role_principal, user_principal,
    )

    assert decode_principal(user_principal(5)) == ("user", 5)
    assert decode_principal(dept_principal(3)) == ("dept", 3)
    assert decode_principal(role_principal(2)) == ("role", 2)
    assert decode_principal(group_principal(7)) == ("group", 7)
    assert decode_principal(PUBLIC)[0] == "public"


def test_acl_endpoint_returns_principal_name():
    """文档 ACL 接口应返回可读的主体名称，而非只有裸 ID。"""
    import inspect

    from app.api.v1.document import get_doc_acl

    src = inspect.getsource(get_doc_acl)
    assert "principal_name" in src
    assert "describe_principals" in src
