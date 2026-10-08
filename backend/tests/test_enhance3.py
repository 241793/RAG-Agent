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
