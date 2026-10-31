#!/usr/bin/env python3
"""本地 OCR 可复现基准：合成图 → OCR → CER / 耗时。

用法：
    python scripts/ocr_benchmark.py                    # 合成 1600x900 中英混排图
    python scripts/ocr_benchmark.py --image shot.png   # 指定图片（需 --truth）
    python scripts/ocr_benchmark.py --runs 5 --json

依赖：Pillow（生成合成图）+ 可选 OCR 引擎（rapidocr/onnxruntime 或 tesseract）。
未安装 OCR 引擎时只打印能力位与安装提示，不报错。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_TEXT = [
    "Sage 本地 OCR 基准测试",
    "Project: Sage Desktop Assistant",
    "Date: 2026-10-31   Version: 0.4.9-alpha.71",
    "1. 统一 OCR 服务（Tesseract + RapidOCR）",
    "2. 无视觉模型时的聊天兜底",
    "3. Office/PDF 扫描页识别",
    "4. Wiki 图片摄入回退",
    "5. 设置页本地 OCR 面板",
    "Invoice No: A-1024   Total: 88.00 CNY",
    "Thank you for using Sage.",
]


def _generate_image(path: Path, lines: list) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 36
    )
    small = ImageFont.truetype(
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 28
    )
    image = Image.new("RGB", (1600, 900), "white")
    draw = ImageDraw.Draw(image)
    y = 50
    for index, line in enumerate(lines):
        draw.text((50, y), line, font=font if index == 0 else small, fill="black")
        y += 80
    image.save(path)


def _normalize(text: str) -> str:
    return " ".join((text or "").split())


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, ch_left in enumerate(left, 1):
        current = [i]
        for j, ch_right in enumerate(right, 1):
            current.append(
                min(
                    current[j - 1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (ch_left != ch_right),
                )
            )
        previous = current
    return previous[-1]


def _cer(truth: str, predicted: str) -> float:
    truth_n = _normalize(truth)
    predicted_n = _normalize(predicted)
    if not truth_n:
        return 0.0
    return _levenshtein(truth_n, predicted_n) / len(truth_n)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local OCR benchmark")
    parser.add_argument("--image", help="使用指定图片（需同时提供 --truth）")
    parser.add_argument("--truth", help="指定图片的真实文本")
    parser.add_argument("--runs", type=int, default=3, help="识别次数（默认 3）")
    parser.add_argument("--max-side", type=int, default=1280, help="长边上限")
    parser.add_argument("--use-cls", action="store_true", help="开启方向分类")
    parser.add_argument("--lang", default="auto", help="auto/ch/en")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    from backend.services.ocr import OcrConfig, OcrService

    config = OcrConfig(
        enabled=True,
        engine="auto",
        lang=args.lang,
        max_side=args.max_side,
        use_cls=args.use_cls,
    )
    service = OcrService(config_provider=lambda: config)
    caps = service.capabilities()
    if not caps.get("available"):
        print("OCR 引擎不可用：", caps.get("reason"))
        print('安装提示：pip install "rapidocr>=3.10,<4" "onnxruntime==1.19.2"')
        return 1

    cleanup_path = None
    if args.image:
        image_path = Path(args.image)
        truth = args.truth or ""
    else:
        truth = args.truth or "\n".join(_DEFAULT_TEXT)
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        cleanup_path = Path(handle.name)
        handle.close()
        try:
            _generate_image(cleanup_path, _DEFAULT_TEXT)
        except Exception as exc:  # noqa: BLE001 — 缺字体/无 Pillow 时给出可读提示
            print("生成合成图失败：", exc)
            print("请安装 Pillow 与 Noto CJK 字体，或使用 --image/--truth。")
            return 2
        image_path = cleanup_path

    try:
        # 预热：排除模型加载时间
        service.recognize_path(str(image_path))
        service.clear_cache()
        times = []
        result = None
        for _ in range(max(1, args.runs)):
            started = time.monotonic()
            result = service.recognize_path(str(image_path))
            times.append(int((time.monotonic() - started) * 1000))
            service.clear_cache()
    finally:
        if cleanup_path is not None:
            try:
                cleanup_path.unlink()
            except OSError:
                pass

    assert result is not None
    payload = {
        "engine": result.engine,
        "quality": result.quality,
        "error": result.error,
        "runs_ms": times,
        "median_ms": sorted(times)[len(times) // 2],
        "cer": round(_cer(truth, result.text), 4) if truth else None,
        "text": result.text,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"engine={payload['engine']} quality={payload['quality']} error={payload['error']}")
        print(f"runs_ms={times} median={payload['median_ms']}ms cer={payload['cer']}")
        print("text:")
        print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
