"""存储适配器：本地磁盘实现（预留 S3/MinIO）。"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from app.core.config import settings


class LocalStorage:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or settings.storage_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, *, tenant_id: int, filename: str, data: bytes) -> tuple[str, str]:
        """保存文件，返回 (file_key, content_hash)。"""
        content_hash = hashlib.sha256(data).hexdigest()
        ext = Path(filename).suffix
        key = f"{tenant_id}/{uuid.uuid4().hex}{ext}"
        dest = self.base_dir / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return key, content_hash

    def path(self, file_key: str, *, tenant_id: int | None = None) -> Path:
        p = (self.base_dir / file_key).resolve()
        # 防路径穿越
        if not str(p).startswith(str(self.base_dir.resolve())):
            raise ValueError("非法 file_key")
        # 可选租户前缀校验
        if tenant_id is not None and not file_key.startswith(f"{tenant_id}/"):
            raise ValueError("跨租户访问")
        return p

    def read(self, file_key: str) -> bytes:
        return self.path(file_key).read_bytes()

    def delete(self, file_key: str) -> None:
        p = self.path(file_key)
        if p.exists():
            p.unlink()


def get_storage() -> LocalStorage:
    return LocalStorage()
