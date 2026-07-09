#!/bin/bash
# Sage 服务监控脚本
# 监控后端 (8765) 和前端 (1420) 状态

BACKEND_URL="http://127.0.0.1:8765/health"
FRONTEND_URL="http://127.0.0.1:1420"
CHECK_INTERVAL=5
LOG_FILE="/tmp/sage_monitor.log"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "🔍 Sage 服务监控启动"
echo "   后端: $BACKEND_URL"
echo "   前端: $FRONTEND_URL"
echo "   检查间隔: ${CHECK_INTERVAL}s"
echo "   日志: $LOG_FILE"
echo "   按 Ctrl+C 停止"
echo "=================================="

check_service() {
    local name=$1
    local url=$2
    local status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$url" 2>/dev/null)

    if [ "$status" = "200" ]; then
        echo -e "${GREEN}✓${NC} [$name] 运行正常 (HTTP $status)" | tee -a "$LOG_FILE"
        return 0
    else
        echo -e "${RED}✗${NC} [$name] 离线 (HTTP $status)" | tee -a "$LOG_FILE"
        return 1
    fi
}

trap 'echo -e "\n${YELLOW}监控停止${NC}"; exit 0' INT TERM

while true; do
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "\n[$timestamp]" | tee -a "$LOG_FILE"

    check_service "后端" "$BACKEND_URL"
    check_service "前端" "$FRONTEND_URL"

    sleep "$CHECK_INTERVAL"
done
