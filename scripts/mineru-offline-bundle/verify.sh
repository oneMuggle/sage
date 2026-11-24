#!/usr/bin/env bash
# =============================================================================
# MinerU 内网离线部署 — 安装后验收（只读，不修改任何状态）
#
# 用法：
#   sudo ./verify.sh [--port 8000]
#
# 检查项：包完整性 / systemd 状态 / GPU / 鉴权配置 / 健康端点 /
#         鉴权实测（受保护端点）/ 模型档位 / 模型目录
# 退出码：0 全通过；1 有 FAIL
#
# 鉴权判定说明：/v1/health、/v1/models、/v1/tiers 是公开端点，不能用来
# 判断鉴权是否生效；必须探测 /v1/usage（非公开）。无凭据 200 ⇒ 匿名，
# 401/403 ⇒ Bearer 生效。本脚本只输出判定结果，不回显密钥。
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORT=""
FAILED=0
ENV_FILE=/etc/mineru/mineru.env
AUTH_MODE_FILE=/etc/mineru/auth-mode
WRAPPER=/etc/mineru/mineru-start.sh
UNIT_FILE=/etc/systemd/system/mineru.service

log()  { printf '\033[1;32m[verify]\033[0m %s\n' "$*"; }
pass() { printf '  \033[1;32mPASS\033[0m  %s\n' "$*"; }
fail() { printf '  \033[1;31mFAIL\033[0m  %s\n' "$*" >&2; FAILED=1; }
warn() { printf '  \033[1;33mWARN\033[0m  %s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    -h|--help) sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf '未知参数: %s\n' "$1" >&2; exit 1 ;;
  esac
done

# --- 1. 离线包完整性 -------------------------------------------------------------
log "1) 离线包完整性"
if [ -f "$SCRIPT_DIR/MANIFEST.env" ]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/MANIFEST.env"
  pass "MANIFEST.env：mineru ${MINERU_VERSION} / python ${PY_FULL_VERSION} / ${BUILD_DATE}"
else
  fail "缺少 MANIFEST.env"
fi

for f in python wheels models install.sh verify.sh config/config.yaml.template \
         systemd/mineru.service.template systemd/mineru-start.sh.template \
         systemd/mineru-start-anonymous.sh.template systemd/mineru.env.template; do
  if [ -e "$SCRIPT_DIR/$f" ]; then pass "$f"; else fail "缺少 $f"; fi
done

# --- 2. systemd 服务状态 ---------------------------------------------------------
log "2) 服务状态"
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet mineru; then
    pass "mineru.service active"
  else
    fail "mineru.service 未运行（journalctl -u mineru -n 100 --no-pager）"
  fi
  if systemctl is-enabled --quiet mineru 2>/dev/null; then
    pass "开机自启已启用"
  else
    warn "开机自启未启用（systemctl enable mineru）"
  fi
else
  warn "无 systemctl，跳过服务状态（手动启动模式）"
fi

if [ -f "$UNIT_FILE" ]; then
  if grep -q '^ExecStart=/etc/mineru/mineru-start.sh' "$UNIT_FILE"; then
    pass "unit ExecStart 指向启动包装脚本"
  else
    fail "unit ExecStart 未指向 $WRAPPER（--api-key 不会生效，服务端会匿名）"
  fi
  if grep -q '^EnvironmentFile=/etc/mineru/mineru.env' "$UNIT_FILE"; then
    pass "unit 引用 /etc/mineru/mineru.env"
  else
    warn "unit 未引用 /etc/mineru/mineru.env"
  fi
else
  warn "缺少 $UNIT_FILE（手动启动模式？）"
fi

if [ -x "$WRAPPER" ]; then
  pass "启动包装脚本可执行：$WRAPPER"
  if grep -q -- '--api-key' "$WRAPPER"; then
    pass "包装脚本会传递 --api-key（bearer 模式）"
    EXPECTED_WRAPPER_MODE=bearer
  else
    pass "包装脚本不传 --api-key（anonymous 模式）"
    EXPECTED_WRAPPER_MODE=anonymous
  fi
else
  fail "缺少可执行启动包装脚本：$WRAPPER"
  EXPECTED_WRAPPER_MODE=unknown
fi

# 未显式指定端口时，从包装脚本解析（兼容旧 unit）
if [ -z "$PORT" ] && [ -f "$WRAPPER" ]; then
  PORT="$(grep -o -- '--port [0-9]\+' "$WRAPPER" | awk '{print $2}' | head -1)"
fi
if [ -z "$PORT" ] && [ -f "$UNIT_FILE" ]; then
  PORT="$(grep -o -- '--port [0-9]\+' "$UNIT_FILE" | awk '{print $2}' | head -1)"
fi
PORT="${PORT:-8000}"
log "   端口：$PORT"
BASE="http://127.0.0.1:${PORT}"

# --- 3. GPU ---------------------------------------------------------------------
log "3) GPU"
if command -v nvidia-smi >/dev/null 2>&1; then
  if gpu="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null)"; then
    pass "GPU：$(printf '%s' "$gpu" | head -1)"
  else
    fail "nvidia-smi 执行失败"
  fi
else
  fail "未找到 nvidia-smi（驱动未装或不在 PATH）"
fi

# --- 4. 鉴权配置 -----------------------------------------------------------------
log "4) 鉴权配置"
API_KEY=""
if [ -f "$ENV_FILE" ]; then
  API_KEY="$(sed -n 's/^MINERU_API_KEY=//p' "$ENV_FILE" | head -1)"
  if [ -n "$API_KEY" ]; then
    pass "已配置 API key（不回显）"
  else
    warn "mineru.env 中 API key 为空（匿名模式可见此项）"
  fi
  mode="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo '?')"
  if [ "$mode" = "600" ]; then pass "env 文件权限 600"; else warn "env 文件权限为 $mode（建议 600）"; fi
else
  fail "缺少 $ENV_FILE"
fi

EXPECTED_MODE="legacy"
if [ -f "$AUTH_MODE_FILE" ]; then
  EXPECTED_MODE="$(tr -d '[:space:]' < "$AUTH_MODE_FILE")"
  pass "期望鉴权模式：$EXPECTED_MODE（$AUTH_MODE_FILE）"
else
  warn "缺少 $AUTH_MODE_FILE（旧版安装）；鉴权期望以实测为准"
fi

if [ "$EXPECTED_MODE" != "legacy" ] && [ "$EXPECTED_WRAPPER_MODE" != "unknown" ] \
   && [ "$EXPECTED_MODE" != "$EXPECTED_WRAPPER_MODE" ]; then
  fail "auth-mode=$EXPECTED_MODE 与包装脚本形态（$EXPECTED_WRAPPER_MODE）不一致"
fi

# --- 5. 健康端点 -----------------------------------------------------------------
log "5) /v1/health（公开端点）"
if curl -sf --max-time 10 -o /dev/null "$BASE/v1/health" 2>/dev/null; then
  pass "健康检查通过"
else
  fail "健康检查失败（$BASE/v1/health）"
fi

# --- 6. 鉴权实测（受保护端点） -----------------------------------------------------
log "6) 鉴权实测：/v1/usage（非公开端点）"
probe_code() {
  local with_auth="$1" raw=""
  if [ "$with_auth" = "1" ] && [ -n "$API_KEY" ]; then
    raw="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
      -H "Authorization: Bearer $API_KEY" "$BASE/v1/usage" 2>/dev/null)" || true
  else
    raw="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
      "$BASE/v1/usage" 2>/dev/null)" || true
  fi
  printf '%s' "${raw:-000}"
}

anon_code="$(probe_code 0)"
auth_code="$(probe_code 1)"
ACTUAL_MODE="unknown"
case "$anon_code" in
  200)     ACTUAL_MODE="anonymous" ;;
  401|403) ACTUAL_MODE="bearer" ;;
esac

access_level=""
if [ "$auth_code" = "200" ] && [ -n "$API_KEY" ]; then
  usage_body="$(curl -s --max-time 10 -H "Authorization: Bearer $API_KEY" \
    "$BASE/v1/usage" 2>/dev/null)" || true
  access_level="$(printf '%s' "$usage_body" \
    | sed -n 's/.*"access_level"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
fi

case "$EXPECTED_MODE" in
  bearer)
    case "$ACTUAL_MODE" in
      bearer)
        if [ "$auth_code" = "200" ]; then
          pass "Bearer 生效（无凭据 ${anon_code}；带 key ${auth_code}；access_level=${access_level:-未知}）"
        else
          fail "Bearer 生效但携带 key 请求返回 ${auth_code}（key 不匹配？）"
        fi
        ;;
      anonymous)
        fail "期望 bearer，但无凭据访问 /v1/usage 返回 ${anon_code}"
        fail "  ⇒ --api-key 未传到 api-server（检查包装脚本 / unit），服务端实际匿名"
        ;;
      *)
        fail "无法判定鉴权（/v1/usage HTTP ${anon_code}）"
        ;;
    esac
    ;;
  anonymous)
    case "$ACTUAL_MODE" in
      anonymous)
        pass "匿名模式生效（无凭据 ${anon_code}）"
        warn "匿名模式：任何可达 ${PORT} 端口的主机都能调用解析服务，请确认内网边界/防火墙"
        ;;
      bearer)
        warn "auth-mode=anonymous，但服务端实际要求鉴权（残留旧 wrapper / drop-in？）"
        ;;
      *)
        fail "无法判定鉴权（/v1/usage HTTP ${anon_code}）"
        ;;
    esac
    ;;
  *)
    case "$ACTUAL_MODE" in
      anonymous)
        warn "旧版安装无 auth-mode 记录；当前服务端匿名（MINERU_API_KEY 未生效）"
        warn "建议重跑 install.sh（默认 bearer）或显式 --auth-mode anonymous"
        ;;
      bearer)
        warn "旧版安装无 auth-mode 记录；当前服务端已要求鉴权"
        ;;
      *)
        fail "无法判定鉴权（/v1/usage HTTP ${anon_code}）"
        ;;
    esac
    ;;
esac

# --- 7. 模型档位（公开端点） -------------------------------------------------------
log "7) /v1/tiers（公开端点）"
tiers_json="$(curl -sf --max-time 10 "$BASE/v1/tiers" 2>/dev/null || true)"
if [ -n "$tiers_json" ]; then
  pass "端点可用"
  printf '%s\n' "$tiers_json" | head -c 500
  printf '\n'
else
  fail "无法读取 /v1/tiers"
fi

# --- 8. 模型离线可解析 -----------------------------------------------------------
log "8) 模型目录"
SVC_HOME=""
if [ -f "$UNIT_FILE" ]; then
  SVC_HOME="$(grep -o '^Environment=HOME=.*' "$UNIT_FILE" | head -1 | cut -d= -f3)"
fi
SVC_HOME="${SVC_HOME:-/var/lib/mineru}"
MODEL_DIR="$SVC_HOME/.mineru/models"
CONFIG="$SVC_HOME/.mineru/config.yaml"
if [ -d "$MODEL_DIR" ]; then
  pass "$MODEL_DIR（$(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1)）"
else
  fail "模型目录不存在：$MODEL_DIR"
fi
if [ -f "$CONFIG" ]; then
  if grep -q 'source: *local' "$CONFIG"; then
    pass "config.yaml source: local"
  else
    fail "config.yaml 未设 source: local（内网卡联网探测）"
  fi
else
  fail "缺少 $CONFIG"
fi

# --- 汇总 -----------------------------------------------------------------------
echo
if [ "$FAILED" = "0" ]; then
  log "全部通过。Sage 客户端可指向：$BASE"
  log "serverAuthMode=${ACTUAL_MODE}（期望 ${EXPECTED_MODE}）"
  exit 0
else
  printf '\033[1;31m[verify]\033[0m 存在 FAIL 项，见上。\n' >&2
  printf '\033[1;31m[verify]\033[0m serverAuthMode=%s（期望 %s）\n' "$ACTUAL_MODE" "$EXPECTED_MODE" >&2
  exit 1
fi
