"""生成应用图标（多尺寸 .ico + .png）。

品牌：深蓝渐变 + 白色 RAG 字样 + 知识库书本意象。
用法：python scripts/make_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent  # 项目根（scripts 的上级）
DESKTOP_DIR = OUT_DIR / "desktop"


def _font(size: int):
    # 尝试常见中英文字体
    for name in ("arialbd.ttf", "arial.ttf", "seguisb.ttf", "msyhbd.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_icon(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角矩形底板（深蓝渐变模拟：用两层叠加）
    radius = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=(0, 32, 74, 255))
    # 顶部高光
    d.rounded_rectangle([0, 0, size - 1, int(size * 0.5)], radius=radius, fill=(0, 58, 112, 255))
    d.rectangle([0, int(size * 0.35), size - 1, size - 1], fill=(0, 40, 88, 255))
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, outline=(22, 119, 255, 255), width=max(2, size // 64))

    # 中间书本图标（简化为三条横线代表文档）
    pad = int(size * 0.24)
    line_w = size - pad * 2
    ly = int(size * 0.40)
    for i in range(3):
        y = ly + i * int(size * 0.10)
        w = line_w if i < 2 else int(line_w * 0.6)
        d.rounded_rectangle([pad, y, pad + w, y + int(size * 0.045)], radius=4, fill=(120, 190, 255, 255))

    # 底部 "RAG" 文字
    font = _font(int(size * 0.20))
    text = "RAG"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - tw) / 2 - bbox[0], int(size * 0.72) - bbox[1]), text, font=font, fill=(255, 255, 255, 255))
    return img


def main() -> None:
    DESKTOP_DIR.mkdir(exist_ok=True)
    base = make_icon(512)
    png_path = DESKTOP_DIR / "icon.png"
    ico_path = DESKTOP_DIR / "icon.ico"
    base.save(png_path)
    # 多尺寸 ico（Windows 常用）
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(ico_path, format="ICO", sizes=sizes)
    print(f"生成: {png_path}")
    print(f"生成: {ico_path}")


if __name__ == "__main__":
    main()
