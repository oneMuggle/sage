#!/usr/bin/env python3
"""
apply-icon-mask.py — Post-process build/icon.png to make outside-rounded-corners
fully transparent.

设计目标
========
- 与 public/sage.svg 的圆角比例保持一致（viewBox 64×64, rx=12 → 比例 12/64 = 0.1875）
- 圆角外区域 alpha=0，圆角内保留原始设计（薄荷绿 + 紫色三角 + 白 S）
- ICO 多分辨率版本（16/24/32/48/64/128/256）从已蒙版的 master PNG 缩放生成
  → PIL LANCZOS 缩放天然保留 alpha 通道
- 强制原地覆盖 build/icon.png + build/icon.ico

调用方式
========
$ python build/source/apply-icon-mask.py

依赖：PIL（conda env sage-backend 已装 Pillow）
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent.parent
ICON_PNG = ROOT / 'build' / 'icon.png'
ICON_ICO = ROOT / 'build' / 'icon.ico'

# 与 sage.svg 的圆角比例保持一致：rx=12 / 64 = 0.1875
# 改这里必须同步改 public/sage.svg 的 rx
ROUNDED_RADIUS_RATIO = 12 / 64

# Windows ICO 标准多分辨率（tray + desktop shortcut 需要）
ICO_SIZES: list[tuple[int, int]] = [
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
]


def make_rounded_mask(size: int) -> Image.Image:
    """生成 size×size 的 L 模式圆角蒙版：圆角内=255, 外=0"""
    mask = Image.new('L', (size, size), 0)
    radius = round(size * ROUNDED_RADIUS_RATIO)
    draw = ImageDraw.Draw(mask)
    # rounded_rectangle 包含外接矩形（不超出 canvas 边界）
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def apply_rounded_mask(img: Image.Image) -> Image.Image:
    """把 RGBA 图像应用圆角蒙版：圆角外 alpha=0, 圆角内保留"""
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    mask = make_rounded_mask(img.size[0])
    out = img.copy()
    out.putalpha(mask)
    return out


def verify_corners_transparent(img: Image.Image) -> None:
    """校验 4 角 alpha=0 且中心区域设计保留"""
    w, h = img.size
    assert w == h, f'非正方形: {w}x{h}'
    # 4 角
    for name, (x, y) in [('TL', (1, 1)), ('TR', (w - 2, 1)), ('BL', (1, h - 2)), ('BR', (w - 2, h - 2))]:
        a = img.getpixel((x, y))[3]
        assert a == 0, f'角 {name} ({x},{y}) alpha={a}, 应该 = 0'
    # 中心
    cx, cy = w // 2, h // 2
    a = img.getpixel((cx, cy))[3]
    assert a > 200, f'中心 ({cx},{cy}) alpha={a}, 设计应该保留'
    print(f'  ✓ 4 角 alpha=0 + 中心设计保留')


def main() -> int:
    if not ICON_PNG.exists():
        print(f'ERROR: {ICON_PNG} 不存在', file=sys.stderr)
        return 1

    print(f'[1/4] Read {ICON_PNG.relative_to(ROOT)}')
    master = Image.open(ICON_PNG).convert('RGBA')
    print(f'      size={master.size} mode={master.mode}')

    print(f'[2/4] Apply rounded mask (rx ratio={ROUNDED_RADIUS_RATIO}, rx={master.size[0] * ROUNDED_RADIUS_RATIO:.0f} for size={master.size[0]})')
    rounded = apply_rounded_mask(master)
    verify_corners_transparent(rounded)

    print(f'[3/4] Write {ICON_PNG.relative_to(ROOT)}')
    rounded.save(ICON_PNG, format='PNG', optimize=True)

    print(f'[4/4] Regenerate {ICON_ICO.relative_to(ROOT)} (sizes={ICO_SIZES})')
    rounded.save(ICON_ICO, format='ICO', sizes=ICO_SIZES)

    # 二次校验：写回 ICO 后重新打开看 alpha
    print()
    print('=== Post-write verification ===')
    ico = Image.open(ICON_ICO)
    ico.seek(0)
    print(f'ICO first frame: size={ico.size} mode={ico.mode}')
    verify_corners_transparent(ico.convert('RGBA'))

    print()
    print(f'DONE: {ICON_PNG.relative_to(ROOT)} + {ICON_ICO.relative_to(ROOT)} 已圆角外透明')
    return 0


if __name__ == '__main__':
    sys.exit(main())