#!/usr/bin/env bash
# =============================================================================
# MinerU 内网离线部署 — 目标服务器执行（需 root）
#
# 用法：
#   sudo ./install.sh [--prefix /opt/mineru] [--home /var/lib/mineru]
#                     [--user mineru] [--port 8000] [--tier standard]
#                     [--auth-mode bearer|anonymous] [--no-systemd]
#
# 做六件事：便携 Python → venv → 离线装 wheel → 落模型与 config
#           → 环境文件 + API key + 启动包装 → systemd 托管
# 环境变量：SKIP_GPU_CHECK=1 跳过 nvidia-smi 检查
#
# 鉴权说明：mineru-kit api-server 的 --api-key 没有环境变量回退，
# 只有在命令行传参才会开启鉴权。因此本脚本安装 /etc/mineru/mineru-start.sh
# 包装脚本，由它把 MINERU_API_KEY 展开为 --api-key。密钥始终只存在于
# 600 权限的 /etc/mineru/mineru.env，包装脚本本身不含密钥。
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PREFIX=/opt/mineru
SVC_USER=mineru
SVC_HOME=/var/lib/mineru
PORT=8000
TIER=standard
AUTH_MODE=bearer
WITH_SYSTEMD=1
SKIP_GPU_CHECK="${SKIP_GPU_CHECK:-0}"

log()  { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install:warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[install:error]\033[0m %s\n' "$*" >&2; exit 1; }

usage() { sed -n '3,19p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)    PREFIX="$2"; shift 2 ;;
    --home)      SVC_HOME="$2"; shift 2 ;;
    --user)      SVC_USER="$2"; shift 2 ;;
    --port)      PORT="$2"; shift 2 ;;
    --tier)      TIER="$2"; shift 2 ;;
    --auth-mode) AUTH_MODE="$2"; shift 2 ;;
    --no-systemd) WITH_SYSTEMD=0; shift ;;
    -h|--help)   usage; exit 0 ;;
    *) die "未知参数: $1（--help 查看用法）" ;;
  esac
done

case "$AUTH_MODE" in
  bearer)    ;;
  anonymous) ;;
  *) die "无效的 --auth-mode: $AUTH_MODE（可选 bearer / anonymous）" ;;
esac

[ "$(id -u)" -eq 0 ] || die "需以 root 执行（sudo ./install.sh）"
[ -f "$SCRIPT_DIR/MANIFEST.env" ] || die "不是完整离线包：缺少 MANIFEST.env"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/MANIFEST.env"

log "离线包版本：mineru ${MINERU_VERSION} / python ${PY_FULL_VERSION} / 构建于 ${BUILD_DATE} (${BUILD_PLATFORM})"
log "鉴权模式：${AUTH_MODE}"

SPECS=("$MINERU_SPEC")
if [ -n "${EXTRA_SPEC:-}" ]; then
  read -r -a _extra <<< "$EXTRA_SPEC"
  SPECS+=("${_extra[@]}")
  log "附加版本约束：$EXTRA_SPEC"
fi

for f in python wheels models install.sh verify.sh config/config.yaml.template \
         systemd/mineru.service.template systemd/mineru-start.sh.template \
         systemd/mineru-start-anonymous.sh.template systemd/mineru.env.template; do
  [ -e "$SCRIPT_DIR/$f" ] || die "离线包不完整：缺少 $f"
done

if [ "$SKIP_GPU_CHECK" != "1" ]; then
  command -v nvidia-smi >/dev/null 2>&1 || die "未检测到 nvidia-smi。确认已装 NVIDIA 驱动 ≥535（跳过检查：SKIP_GPU_CHECK=1）"
  nvidia-smi -L || die "nvidia-smi 执行失败，驱动异常"
fi

# 旧版部署检测：unit 里既没有包装脚本也没有 --api-key ⇒ 服务端实际为匿名
LEGACY_AUTH_OFF=0
UNIT_FILE=/etc/systemd/system/mineru.service
if [ -f "$UNIT_FILE" ] && ! grep -q 'mineru-start\.sh' "$UNIT_FILE"; then
  if ! grep -q -- '--api-key' "$UNIT_FILE"; then
    LEGACY_AUTH_OFF=1
  fi
fi

# --- 1. 服务用户 ---------------------------------------------------------------
if ! id "$SVC_USER" >/dev/null 2>&1; then
  log "创建系统用户 $SVC_USER（home=$SVC_HOME）"
  useradd --system --home-dir "$SVC_HOME" --create-home --shell /usr/sbin/nologin "$SVC_USER"
else
  log "用户 $SVC_USER 已存在"
fi

# --- 2. 便携 Python ------------------------------------------------------------
PYBIN="$PREFIX/python/bin/python${PY_VERSION}"
if [ ! -x "$PYBIN" ]; then
  log "安装便携 Python 到 $PREFIX/python"
  install -d "$PREFIX"
  cp -a "$SCRIPT_DIR/python" "$PREFIX/"
else
  log "便携 Python 已存在，跳过"
fi
[ -x "$PYBIN" ] || die "便携 Python 不可执行：$PYBIN"

# --- 3. venv + 离线 wheel 安装 ---------------------------------------------------
if [ ! -x "$PREFIX/.venv/bin/python" ]; then
  log "创建 venv：$PREFIX/.venv"
  "$PYBIN" -m venv --copies "$PREFIX/.venv"
fi

log "离线安装 $MINERU_SPEC（--no-index）..."
"$PREFIX/.venv/bin/pip" install \
  --no-index --find-links "$SCRIPT_DIR/wheels" --no-cache-dir "${SPECS[@]}"

# --- 4. 模型与配置 --------------------------------------------------------------
MODEL_DIR="$SVC_HOME/.mineru/models"
install -d -o "$SVC_USER" -g "$SVC_USER" "$SVC_HOME/.mineru"
if [ ! -d "$MODEL_DIR" ]; then
  log "落模型到 $MODEL_DIR"
  cp -a "$SCRIPT_DIR/models" "$MODEL_DIR"
else
  log "模型目录已存在，跳过（如需重装请先删除 $MODEL_DIR）"
fi
chown -R "$SVC_USER:$SVC_USER" "$SVC_HOME/.mineru"

log "生成 config：$SVC_HOME/.mineru/config.yaml（source: local）"
sed -e "s#__MINERU_MODEL_DIR__#${MODEL_DIR}#g" \
    -e "s#__SMALL_BACKEND__#${SMALL_BACKEND:-torch}#g" \
    -e "s#__VLM_ENGINE__#${VLM_ENGINE:-vllm}#g" \
  "$SCRIPT_DIR/config/config.yaml.template" > "$SVC_HOME/.mineru/config.yaml"
chown "$SVC_USER:$SVC_USER" "$SVC_HOME/.mineru/config.yaml"

# --- 5. 环境文件与 API key -------------------------------------------------------
install -d -m 755 /etc/mineru
ENV_FILE=/etc/mineru/mineru.env
AUTH_MODE_FILE=/etc/mineru/auth-mode

EXISTING_KEY=""
if [ -f "$ENV_FILE" ]; then
  EXISTING_KEY="$(sed -n 's/^MINERU_API_KEY=//p' "$ENV_FILE" | head -1)"
fi

API_KEY=""
if [ "$AUTH_MODE" = "bearer" ]; then
  if [ -n "$EXISTING_KEY" ]; then
    API_KEY="$EXISTING_KEY"
    log "复用已有 API key（$ENV_FILE）"
  else
    command -v openssl >/dev/null 2>&1 || die "缺少 openssl，无法生成 API key"
    API_KEY="$(openssl rand -hex 32)"
    log "已生成 API key 到 $ENV_FILE（600）"
  fi
else
  # 匿名模式：保留旧 key 原值（便于日后切回 bearer），服务端不会收到它
  API_KEY="$EXISTING_KEY"
  log "匿名模式：不启用服务端鉴权"
fi

ENV_TMP="$(mktemp)"
sed -e "s|__API_KEY__|${API_KEY}|" "$SCRIPT_DIR/systemd/mineru.env.template" > "$ENV_TMP"
install -m 0600 -o root -g root "$ENV_TMP" "$ENV_FILE"
rm -f "$ENV_TMP"

printf '%s\n' "$AUTH_MODE" > "$AUTH_MODE_FILE"
chmod 0644 "$AUTH_MODE_FILE"

# --- 6. 启动包装脚本 -------------------------------------------------------------
WRAPPER=/etc/mineru/mineru-start.sh
if [ "$AUTH_MODE" = "bearer" ]; then
  WRAPPER_TPL="$SCRIPT_DIR/systemd/mineru-start.sh.template"
else
  WRAPPER_TPL="$SCRIPT_DIR/systemd/mineru-start-anonymous.sh.template"
fi
WRAPPER_TMP="$(mktemp)"
sed -e "s|__PREFIX__|${PREFIX}|g" \
    -e "s|__PORT__|${PORT}|g" \
    -e "s|__TIER__|${TIER}|g" \
  "$WRAPPER_TPL" > "$WRAPPER_TMP"
install -m 0755 -o root -g root "$WRAPPER_TMP" "$WRAPPER"
rm -f "$WRAPPER_TMP"
log "启动包装脚本：$WRAPPER（无密钥，0755）"

# --- 7. systemd 托管 -------------------------------------------------------------
if [ "$WITH_SYSTEMD" = "1" ]; then
  command -v systemctl >/dev/null 2>&1 || die "无 systemctl，请改用 --no-systemd 手动启动"
  UNIT_TMP="$(mktemp)"
  sed -e "s#__USER__#${SVC_USER}#g" \
      -e "s#__HOME__#${SVC_HOME}#g" \
    "$SCRIPT_DIR/systemd/mineru.service.template" > "$UNIT_TMP"
  install -m 0644 -o root -g root "$UNIT_TMP" "$UNIT_FILE"
  rm -f "$UNIT_TMP"
  systemctl daemon-reload
  systemctl enable mineru >/dev/null 2>&1 || true
  systemctl restart mineru
  log "systemd 服务已启动：systemctl status mineru"
fi

# --- 8. 健康检查与鉴权实测 -------------------------------------------------------
ACTUAL_AUTH_MODE="unknown"
if [ "$WITH_SYSTEMD" = "1" ]; then
  log "等待 /v1/health（最长 300s，vLLM 冷启动较慢）..."
  ok=0
  for _ in $(seq 1 60); do
    if curl -sf --max-time 5 -o /dev/null "http://127.0.0.1:${PORT}/v1/health"; then ok=1; break; fi
    sleep 5
  done
  if [ "$ok" = "1" ]; then
    log "健康检查通过"
  else
    warn "300s 内未就绪；排查：journalctl -u mineru -n 100 --no-pager"
  fi

  # /v1/usage 不是公开端点：无凭据 200 ⇒ 匿名；401/403 ⇒ Bearer 生效
  probe_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
    "http://127.0.0.1:${PORT}/v1/usage" 2>/dev/null || true)"
  probe_code="${probe_code:-000}"
  case "$probe_code" in
    200)       ACTUAL_AUTH_MODE="anonymous" ;;
    401|403)   ACTUAL_AUTH_MODE="bearer" ;;
    *)         ACTUAL_AUTH_MODE="unknown" ;;
  esac
  log "鉴权实测：serverAuthMode=${ACTUAL_AUTH_MODE}（HTTP ${probe_code} on /v1/usage）"

  if [ "$AUTH_MODE" = "bearer" ] && [ "$ACTUAL_AUTH_MODE" != "bearer" ]; then
    warn "期望 Bearer 但服务端未要求鉴权。检查 $WRAPPER 是否包含 --api-key，"
    warn "以及 journalctl -u mineru 是否有 wrapper 报错。"
  fi
  if [ "$AUTH_MODE" = "anonymous" ] && [ "$ACTUAL_AUTH_MODE" = "bearer" ]; then
    warn "期望匿名但服务端要求鉴权（可能残留旧 systemd drop-in 或错误 wrapper）。"
  fi
else
  log "已跳过 systemd。手动启动（不把密钥写入 shell 历史）："
  echo "  sudo bash -c 'set -a; . $ENV_FILE; set +a; exec runuser -u $SVC_USER -- env HOME=$SVC_HOME $WRAPPER'"
fi

if [ "$LEGACY_AUTH_OFF" = "1" ]; then
  if [ "$AUTH_MODE" = "bearer" ]; then
    warn "检测到旧部署未启用鉴权；本次已切换为 Bearer。"
    warn "请把 $ENV_FILE 中的 MINERU_API_KEY 填入 Sage 设置页；"
    warn "若暂时不想改动现有客户端，请重跑：sudo ./install.sh --auth-mode anonymous"
  else
    log "检测到旧部署未启用鉴权；本次保持匿名模式（与升级前一致）"
  fi
fi

cat <<EOF

================ 安装完成 ================
服务文件 : $UNIT_FILE
启动包装 : $WRAPPER
环境文件 : $ENV_FILE（600，含 API key，勿外泄）
鉴权模式 : 期望 $AUTH_MODE / 实测 $ACTUAL_AUTH_MODE
模型目录 : $MODEL_DIR
验证命令 : sudo ./verify.sh

Sage 客户端配置（preferences 的 mineru_service）：
{
  "mineru": {
    "baseUrl": "http://<本机内网IP>:${PORT}",
    "apiKey": "<bearer：从 $ENV_FILE 读取 MINERU_API_KEY；anonymous：留空>",
    "defaultTier": "${TIER}",
    "timeoutSeconds": 300
  }
}
serverAuthMode: ${ACTUAL_AUTH_MODE}
==========================================
EOF

if [ "$AUTH_MODE" = "bearer" ]; then
  cat <<EOF
在本机查看 key（不要把输出粘贴到聊天或日志）：
  sudo sed -n 's/^MINERU_API_KEY=//p' $ENV_FILE
EOF
else
  warn "匿名模式：任何能访问 ${PORT} 端口的主机都可调用解析服务，请用内网防火墙限制来源。"
fi
