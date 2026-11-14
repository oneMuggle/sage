#!/usr/bin/env bash
# 下载本地 AI 模型到 resources/models/，供 electron-builder 打包。
#
# 用法:
#   scripts/download-models.sh              # 下载全部模型
#   scripts/download-models.sh ocr          # 仅 OCR
#   scripts/download-models.sh embedder     # 仅 Embedding
#   scripts/download-models.sh --check      # 仅校验已下载文件
#
# 下载产物会被 .gitignore 排除，不进入版本控制。
# CI 打包前必须运行此脚本（GitHub Actions 可访问外网）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODELS_DIR="$REPO_ROOT/resources/models"

# ── 模型清单（sha256 与 electron/modelDownloadIpc.ts 保持一致）──

OCR_BASE="https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/PP-OCRv6"
OCR_FILES=(
  "det/PP-OCRv6_det_tiny.onnx:rapidocr/det.onnx:f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5"
  "rec/PP-OCRv6_rec_tiny.onnx:rapidocr/rec.onnx:e16e242de5937ad92609223f19bc2aff3727ee40b095f996907c24749bad251b"
)

EMBEDDER_BASE="https://hf-mirror.com/Xenova/bge-small-zh-v1.5/resolve/main"
EMBEDDER_FILES=(
  "tokenizer.json:bge-small-zh-v1.5/tokenizer.json:48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26"
  "onnx/model.onnx:bge-small-zh-v1.5/model.onnx:69a0b846f4f116b5e6aabf9546ea6754d02264f3211a13a1bd69b31b8040749a"
)

# ── 颜色 ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

download_file() {
  local url="$1" dest="$2" expected_sha="$3" label="$4"

  if [[ -f "$dest" ]]; then
    local actual
    actual=$(sha256sum "$dest" | cut -d' ' -f1)
    if [[ "$actual" == "$expected_sha" ]]; then
      echo -e "  ${GREEN}✓${NC} $label (已存在，校验通过)"
      return 0
    fi
    echo -e "  ${YELLOW}⚠${NC} $label (已存在但校验失败，重新下载)"
    rm -f "$dest"
  fi

  mkdir -p "$(dirname "$dest")"
  echo -n "  下载 $label ... "
  if curl -fsSL -o "$dest" "$url"; then
    local actual
    actual=$(sha256sum "$dest" | cut -d' ' -f1)
    if [[ "$actual" == "$expected_sha" ]]; then
      echo -e "${GREEN}✓${NC}"
    else
      echo -e "${RED}✗ sha256 不匹配${NC}"
      echo "    期望: $expected_sha"
      echo "    实际: $actual"
      rm -f "$dest"
      return 1
    fi
  else
    echo -e "${RED}✗ 下载失败${NC}"
    rm -f "$dest"
    return 1
  fi
}

download_ocr() {
  echo "── OCR 模型 (RapidOCR PP-OCRv6 tiny, ~6MB) ──"
  local fail=0
  for entry in "${OCR_FILES[@]}"; do
    IFS=':' read -r remote_path local_path sha <<< "$entry"
    download_file "$OCR_BASE/$remote_path" "$MODELS_DIR/$local_path" "$sha" "$local_path" || fail=1
  done
  return $fail
}

download_embedder() {
  echo "── Embedding 模型 (bge-small-zh-v1.5 ONNX, ~91MB) ──"
  local fail=0
  for entry in "${EMBEDDER_FILES[@]}"; do
    IFS=':' read -r remote_path local_path sha <<< "$entry"
    download_file "$EMBEDDER_BASE/$remote_path" "$MODELS_DIR/$local_path" "$sha" "$local_path" || fail=1
  done
  return $fail
}

check_models() {
  echo "── 校验已下载模型 ──"
  local total=0 ok=0
  for entry in "${OCR_FILES[@]}" "${EMBEDDER_FILES[@]}"; do
    IFS=':' read -r _ local_path sha <<< "$entry"
    total=$((total + 1))
    local dest="$MODELS_DIR/$local_path"
    if [[ -f "$dest" ]]; then
      local actual
      actual=$(sha256sum "$dest" | cut -d' ' -f1)
      if [[ "$actual" == "$sha" ]]; then
        echo -e "  ${GREEN}✓${NC} $local_path"
        ok=$((ok + 1))
      else
        echo -e "  ${RED}✗${NC} $local_path (sha256 不匹配)"
      fi
    else
      echo -e "  ${RED}✗${NC} $local_path (不存在)"
    fi
  done
  echo ""
  echo "$ok/$total 文件就绪"
  [[ $ok -eq $total ]]
}

# ── 主流程 ──
target="${1:-all}"

case "$target" in
  ocr)      download_ocr ;;
  embedder) download_embedder ;;
  --check)  check_models ;;
  all)
    download_ocr
    echo ""
    download_embedder
    ;;
  *)
    echo "用法: $0 [ocr|embedder|--check]"
    exit 1
    ;;
esac
