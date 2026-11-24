#!/usr/bin/env bash
# =============================================================================
# MinerU 内网离线部署包 — 构建脚本（在联网 Linux x86_64 构建机上执行）
#
# 用法：
#   bash scripts/mineru-offline-bundle/build-bundle.sh
#
# 产出：
#   $OUT_DIR/mineru-offline-bundle-<ver>-<YYYYMMDD>-linux-x86_64.tar
#   $OUT_DIR/mineru-offline-bundle-<ver>-<YYYYMMDD>-linux-x86_64.tar.sha256
#   （wheel 与模型本身已是压缩产物，包体不再 gzip，避免多花 30+ 分钟）
#
# 可覆盖的环境变量：
#   MINERU_SPEC   默认 mineru[full]>=4.1,<4.2
#   EXTRA_SPEC    默认空；例如 vllm==0.19.1（torch 2.10 / CUDA 12.8 / 驱动 ≥535）
#   PY_VERSION    默认 3.12
#   PBS_VERSION   python-build-standalone 发布日期 tag；默认取 latest release
#   PIP_INDEX_URL / PIP_PLATFORM / PIP_ONLY_BINARY
#   MODEL_SOURCE  默认 huggingface（失败自动回退 modelscope）
#   TIER          默认 standard（仅 basic / standard 有对应模型集）
#   SMALL_BACKEND 默认 torch；VLM_ENGINE 默认 vllm
#   OUT_DIR       默认 $HOME/mineru-offline-bundle-out
#   WORK_DIR      默认 $HOME/mineru-bundle-build（构建缓存）
#   KEEP_STAGING=1   保留 $WORK_DIR/staging 便于排障
#   CLEAN_WORK_DIR=1 构建成功后删除 $WORK_DIR（约 15 GB）
#   SKIP_DISK_CHECK=1 跳过磁盘余量检查
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MINERU_SPEC="${MINERU_SPEC:-mineru[full]>=4.1,<4.2}"
EXTRA_SPEC="${EXTRA_SPEC:-}"
PY_VERSION="${PY_VERSION:-3.12}"
PBS_VERSION="${PBS_VERSION:-}"
MODEL_SOURCE="${MODEL_SOURCE:-huggingface}"
TIER="${TIER:-standard}"
SMALL_BACKEND="${SMALL_BACKEND:-torch}"
VLM_ENGINE="${VLM_ENGINE:-vllm}"
OUT_DIR="${OUT_DIR:-$HOME/mineru-offline-bundle-out}"
WORK_DIR="${WORK_DIR:-$HOME/mineru-bundle-build}"
KEEP_STAGING="${KEEP_STAGING:-0}"
CLEAN_WORK_DIR="${CLEAN_WORK_DIR:-0}"
SKIP_DISK_CHECK="${SKIP_DISK_CHECK:-0}"
BUILD_PLATFORM="linux-x86_64"

PBS_API="https://api.github.com/repos/astral-sh/python-build-standalone/releases"

log()  { printf '\033[1;32m[build]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[build:warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[build:error]\033[0m %s\n' "$*" >&2; exit 1; }

# --- 0. 前置检查 -----------------------------------------------------------------
case "$TIER" in
  basic|standard) ;;
  *) die "无效 TIER=$TIER（models download 仅支持 basic / standard）" ;;
esac

[ "$(uname -s)" = "Linux" ] || die "本脚本只支持 Linux 构建机"
case "$(uname -m)" in
  x86_64|amd64) ;;
  *) die "本脚本只支持 x86_64（当前 $(uname -m)）；交叉构建请设 PIP_PLATFORM 并自行验证" ;;
esac

for tool in curl tar python3 sha256sum du awk; do
  command -v "$tool" >/dev/null 2>&1 || die "缺少命令：$tool"
done

mkdir -p "$OUT_DIR" "$WORK_DIR"
if [ "$SKIP_DISK_CHECK" != "1" ]; then
  avail_kb="$(df -Pk "$WORK_DIR" | awk 'NR==2 {print $4}')"
  # python 230M + wheels 5G + models 3.1G，加下载缓存与 staging 副本，留 25 GB 余量
  if [ "${avail_kb:-0}" -lt $((25 * 1024 * 1024)) ]; then
    die "$WORK_DIR 可用空间不足 25 GB（当前 $((avail_kb / 1024 / 1024)) GB）；可设 SKIP_DISK_CHECK=1 跳过"
  fi
fi

# 离线包必须自带部署脚本与模板，缺一个就构建不出可安装的包
for f in install.sh verify.sh README.md config/config.yaml.template \
         systemd/mineru.service.template systemd/mineru-start.sh.template \
         systemd/mineru-start-anonymous.sh.template systemd/mineru.env.template; do
  [ -e "$SCRIPT_DIR/$f" ] || die "仓库内缺少 $f（离线包内容不完整）"
done

DOWNLOAD_DIR="$WORK_DIR/downloads"
mkdir -p "$DOWNLOAD_DIR"

# --- 1. 便携 Python（python-build-standalone） -------------------------------------
rel_json="$DOWNLOAD_DIR/pbs-release.json"
if [ -z "$PBS_VERSION" ]; then
  log "查询 python-build-standalone latest release"
  curl -fsSL --retry 3 -o "$rel_json" "$PBS_API/latest" \
    || die "GitHub API 不可达；可显式指定 PBS_VERSION=<发布日期 tag>"
else
  curl -fsSL --retry 3 -o "$rel_json" "$PBS_API/tags/$PBS_VERSION" \
    || die "无法获取 PBS_VERSION=$PBS_VERSION 的 release 元数据"
fi

PBS_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag_name"])' "$rel_json")"
PBS_ASSET="$(python3 - "$rel_json" "$PY_VERSION" <<'PY'
import json
import re
import sys

data = json.load(open(sys.argv[1]))
ver = re.escape(sys.argv[2])
pattern = re.compile(
    r"^cpython-%s\..*x86_64-unknown-linux-gnu-install_only(?:\.tar\.gz|_stripped\.tar\.gz)$" % ver
)
names = [a["name"] for a in data.get("assets", []) if pattern.match(a["name"])]
# install_only.tar.gz 优先；_stripped 不含调试符号，也可运行
names.sort(key=lambda n: ("_stripped" in n, n))
print(names[0] if names else "")
PY
)"
[ -n "$PBS_ASSET" ] || die "release $PBS_VERSION 中没有 cpython-$PY_VERSION.*x86_64-linux-gnu-install_only 资产"
log "便携 Python：$PBS_ASSET（PBS $PBS_VERSION）"

pbs_tarball="$DOWNLOAD_DIR/$PBS_ASSET"
if [ ! -s "$pbs_tarball" ]; then
  pbs_urls=(
    "https://registry.npmmirror.com/-/binary/python-build-standalone/$PBS_VERSION/$PBS_ASSET"
    "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_VERSION/$PBS_ASSET"
    "https://ghproxy.net/https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_VERSION/$PBS_ASSET"
  )
  got=0
  for url in "${pbs_urls[@]}"; do
    log "下载：$url"
    if curl -fL --retry 3 --connect-timeout 20 -o "$pbs_tarball.part" "$url"; then
      mv "$pbs_tarball.part" "$pbs_tarball"
      got=1
      break
    fi
    warn "失败，尝试下一个镜像"
  done
  [ "$got" = "1" ] || die "便携 Python 下载失败（三个镜像均不可用）"
else
  log "复用已下载的 $PBS_ASSET"
fi

PY_ROOT="$WORK_DIR/python"
if [ ! -x "$PY_ROOT/bin/python${PY_VERSION}" ]; then
  log "解包便携 Python 到 $PY_ROOT"
  rm -rf "$PY_ROOT"
  mkdir -p "$PY_ROOT"
  tar -xzf "$pbs_tarball" -C "$PY_ROOT" --strip-components=1
fi
PYBIN="$PY_ROOT/bin/python${PY_VERSION}"
[ -x "$PYBIN" ] || die "便携 Python 不可执行：$PYBIN"

# --- 2. venv + 升级 pip 工具链 -----------------------------------------------------
VENV="$WORK_DIR/venv"
if [ ! -x "$VENV/bin/python" ]; then
  log "创建 venv（--copies，避免依赖构建机系统 python）"
  "$PYBIN" -m venv --copies "$VENV"
fi

PIP_ARGS=(--disable-pip-version-check)
if [ -n "${PIP_INDEX_URL:-}" ]; then
  PIP_ARGS+=(--index-url "$PIP_INDEX_URL")
fi
"$VENV/bin/python" -m pip install "${PIP_ARGS[@]}" --upgrade pip setuptools wheel

# --- 3. wheel（两阶段：先 download，sdist 再 wheel 化） ----------------------------
SPECS=("$MINERU_SPEC")
if [ -n "$EXTRA_SPEC" ]; then
  read -r -a _extra <<< "$EXTRA_SPEC"
  SPECS+=("${_extra[@]}")
fi
log "解析依赖：${SPECS[*]}"

PIP_DL="$DOWNLOAD_DIR/pip"
WHEELS="$WORK_DIR/wheels"
mkdir -p "$PIP_DL" "$WHEELS"

PLATFORM_ARGS=()
if [ -n "${PIP_PLATFORM:-}" ]; then
  # 交叉下载：只接受目标平台二进制包；--abi 由 Python 版本推出
  PLATFORM_ARGS=(
    --platform "$PIP_PLATFORM"
    --python-version "$PY_VERSION"
    --implementation cp
    --abi "cp${PY_VERSION//./}"
  )
  if [ -n "${PIP_ONLY_BINARY:-}" ]; then
    PLATFORM_ARGS+=("$PIP_ONLY_BINARY")
  fi
fi

if [ "${#PLATFORM_ARGS[@]}" -gt 0 ]; then
  "$VENV/bin/python" -m pip download "${PIP_ARGS[@]}" "${PLATFORM_ARGS[@]}" \
    --dest "$PIP_DL" "${SPECS[@]}"
else
  "$VENV/bin/python" -m pip download "${PIP_ARGS[@]}" --dest "$PIP_DL" "${SPECS[@]}"
fi

log "收集已下载 wheel"
shopt -s nullglob
cp -n "$PIP_DL"/*.whl "$WHEELS"/ 2>/dev/null || true

if [ "${#PLATFORM_ARGS[@]}" -eq 0 ]; then
  for sdist in "$PIP_DL"/*.tar.gz "$PIP_DL"/*.zip; do
    [ -e "$sdist" ] || continue
    log "本地构建 wheel：$(basename "$sdist")"
    "$VENV/bin/python" -m pip wheel "${PIP_ARGS[@]}" --no-deps \
      --wheel-dir "$WHEELS" "$sdist"
  done
fi

if ! compgen -G "$WHEELS/mineru-*.whl" >/dev/null; then
  die "未产出 mineru wheel；检查 $MINERU_SPEC 与 PIP_PLATFORM 组合"
fi

# --- 4. 模型 ---------------------------------------------------------------------
MINERU_HOME="$WORK_DIR/mineru-home"
MODEL_DIR="$MINERU_HOME/.mineru/models"
mkdir -p "$MINERU_HOME"

download_models() {
  local src="$1"
  HOME="$MINERU_HOME" MINERU_MODEL_SOURCE="$src" \
    "$VENV/bin/mineru-kit" models download \
      --tier "$TIER" \
      --small-backend "$SMALL_BACKEND" \
      --vlm-engine "$VLM_ENGINE" \
      --source "$src" \
      --verbose
}

if [ -d "$MODEL_DIR" ] && [ -n "$(ls -A "$MODEL_DIR" 2>/dev/null)" ]; then
  log "复用已有模型目录 $MODEL_DIR"
else
  log "下载模型（tier=$TIER small_backend=$SMALL_BACKEND vlm=$VLM_ENGINE source=$MODEL_SOURCE）"
  if [ "$MODEL_SOURCE" = "huggingface" ]; then
    # HF Xet 传输在内网/代理下常卡死，禁用后回退普通 HTTP
    if ! HF_HUB_DISABLE_XET=1 download_models huggingface; then
      warn "huggingface 下载失败，回退 modelscope"
      download_models modelscope
    fi
  else
    download_models "$MODEL_SOURCE"
  fi
fi

HOME="$MINERU_HOME" MINERU_MODEL_SOURCE=local \
  "$VENV/bin/mineru-kit" models verify \
    --tier "$TIER" --small-backend "$SMALL_BACKEND" --vlm-engine "$VLM_ENGINE" \
  || die "模型校验失败（缺少 vllm 运行时会表现为 models verify 不通过）"

# --- 5. staging 目录 --------------------------------------------------------------
STAGE_ROOT="$WORK_DIR/staging"
BUNDLE_DIRNAME=mineru-offline-bundle
STAGE="$STAGE_ROOT/$BUNDLE_DIRNAME"
rm -rf "$STAGE_ROOT"
mkdir -p "$STAGE"/{config,systemd}

log "复制组件到 staging"
cp -a "$PY_ROOT" "$STAGE/python"
cp -a "$WHEELS" "$STAGE/wheels"
cp -a "$MODEL_DIR" "$STAGE/models"
cp "$SCRIPT_DIR/install.sh" "$SCRIPT_DIR/verify.sh" "$SCRIPT_DIR/README.md" "$STAGE/"
cp "$SCRIPT_DIR/config/config.yaml.template" "$STAGE/config/"
cp "$SCRIPT_DIR"/systemd/*.template "$STAGE/systemd/"
chmod 0755 "$STAGE/install.sh" "$STAGE/verify.sh"

MINERU_VERSION="$(HOME="$MINERU_HOME" "$VENV/bin/python" -c \
  'import importlib.metadata as m; print(m.version("mineru"))')"
PY_FULL_VERSION="$(HOME="$MINERU_HOME" "$VENV/bin/python" -c \
  'import platform; print(platform.python_version())')"
BUILD_DATE="$(date +%Y%m%d)"

cat > "$STAGE/MANIFEST.env" <<EOF
MINERU_SPEC="$MINERU_SPEC"
EXTRA_SPEC="$EXTRA_SPEC"
MINERU_VERSION="$MINERU_VERSION"
PY_VERSION="$PY_VERSION"
PY_FULL_VERSION="$PY_FULL_VERSION"
BUILD_DATE="$BUILD_DATE"
BUILD_PLATFORM="$BUILD_PLATFORM"
TIER="$TIER"
SMALL_BACKEND="$SMALL_BACKEND"
VLM_ENGINE="$VLM_ENGINE"
EOF

{
  echo "MinerU 内网离线部署包"
  echo "version      : $MINERU_VERSION"
  echo "python       : $PY_FULL_VERSION"
  echo "build date   : $BUILD_DATE"
  echo "platform     : $BUILD_PLATFORM"
  echo "spec         : $MINERU_SPEC${EXTRA_SPEC:+ + $EXTRA_SPEC}"
  echo "tier         : $TIER (small-backend=$SMALL_BACKEND, vlm-engine=$VLM_ENGINE)"
  echo "systemd      : mineru.service + /etc/mineru/mineru-start.sh"
  echo
  echo "components:"
  (cd "$STAGE" && du -sh python wheels models | awk '{printf "  %-8s %s\n", $1, $2}')
  echo
  echo "usage        : sudo ./install.sh   then   sudo ./verify.sh"
} > "$STAGE/MANIFEST.txt"

# --- 6. 打包 ---------------------------------------------------------------------
OUT_NAME="mineru-offline-bundle-${MINERU_VERSION}-${BUILD_DATE}-${BUILD_PLATFORM}.tar"
log "打包（不加压缩，体积约 8 GB）..."
tar -C "$STAGE_ROOT" -cf "$OUT_DIR/$OUT_NAME" "$BUNDLE_DIRNAME"
( cd "$OUT_DIR" && sha256sum "$OUT_NAME" > "$OUT_NAME.sha256" )

if [ "$KEEP_STAGING" != "1" ]; then
  rm -rf "$STAGE_ROOT"
fi
if [ "$CLEAN_WORK_DIR" = "1" ]; then
  log "清理构建缓存 $WORK_DIR"
  rm -rf "$WORK_DIR"
fi

log "完成"
ls -lh "$OUT_DIR/$OUT_NAME" "$OUT_DIR/$OUT_NAME.sha256"
log "目标机：tar -xf <包名>.tar && cd $BUNDLE_DIRNAME && sudo ./install.sh"
