"""HTTP 响应辅助：安全生成 Content-Disposition 头。

文件名可能含中文等非 ASCII 字符，直接放进 HTTP 头会因 latin-1 编码报
UnicodeEncodeError（表现为下载/预览 500）。按 RFC 5987 用 filename* 传 UTF-8，
并保留一个 ASCII 回退名 filename= 给老客户端。
"""
from __future__ import annotations

from urllib.parse import quote


def content_disposition(filename: str, *, inline: bool = False) -> str:
    """生成安全的 Content-Disposition 值（支持中文等非 ASCII 文件名）。

    inline=True 用于浏览器内联预览（如 HTML/PDF），否则为附件下载。
    """
    disp = "inline" if inline else "attachment"
    name = filename or "file"
    # ASCII 回退：把非 ASCII 字符替换为下划线，避免老客户端乱码/报错
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace('"', "")
    quoted = quote(name, safe="")
    return f"{disp}; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"
