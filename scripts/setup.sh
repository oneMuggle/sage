#!/bin/bash
# Sage 安装脚本 - Linux/macOS
# Windows 7 兼容版本

set -e  # 遇到错误时退出

echo "========================================"
echo "  Sage - 记忆型 AI 助手 安装脚本"
echo "========================================"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查函数
check_command() {
    if command -v "$1" &> /dev/null; then
        echo -e "${GREEN}[✓]${NC} $1: $($1 --version | head -n1)"
        return 0
    else
        echo -e "${RED}[✗]${NC} $1: 未找到"
        return 1
    fi
}

# 进度提示
check_python() {
    echo "[1/5] 检查 Python 环境..."
    if check_command python3; then
        PYTHON_CMD="python3"
    elif check_command python; then
        PYTHON_CMD="python"
    else
        echo -e "${RED}[错误]${NC} 未找到 Python！"
        echo "请先安装 Python 3.8+: https://www.python.org/downloads/"
        exit 1
    fi
    echo ""
}

check_node() {
    echo "[2/5] 检查 Node.js 环境..."
    if check_command node; then
        echo -e "${YELLOW}[提示]${NC} Node.js 已安装"
    else
        echo -e "${RED}[错误]${NC} 未找到 Node.js！"
        echo "请先安装 Node.js 18+: https://nodejs.org/"
        exit 1
    fi
    echo ""
}

check_rust() {
    echo "[5/5] 检查 Rust 环境..."
    if check_command rustc; then
        echo -e "${GREEN}[✓]${NC} Rust 已安装，可以构建 Tauri 应用"
    else
        echo -e "${YELLOW}[警告]${NC} 未检测到 Rust，将无法构建 Tauri 应用"
        echo "请访问 https://rustup.rs 安装 Rust"
    fi
    echo ""
}

# 主流程
main() {
    check_python
    check_node
    
    # 安装 Python 依赖
    echo "[3/5] 安装 Python 依赖..."
    if [ -f "backend/requirements.txt" ]; then
        $PYTHON_CMD -m pip install -r backend/requirements.txt
    else
        echo -e "${YELLOW}[警告]${NC} 未找到 backend/requirements.txt，跳过"
    fi
    echo ""
    
    # 安装 Node.js 依赖
    echo "[4/5] 安装 Node.js 依赖..."
    if [ -f "package.json" ]; then
        npm install
    else
        echo -e "${RED}[错误]${NC} 未找到 package.json"
        exit 1
    fi
    echo ""
    
    check_rust
    
    echo "========================================"
    echo "  安装完成！"
    echo "========================================"
    echo ""
    echo "接下来:"
    echo "  1. 运行 \`npm run tauri dev\` 启动开发模式"
    echo "  2. 或运行 \`npm run tauri build\` 构建应用"
    echo ""
    echo "详细文档请参阅 README.md"
    echo ""
}

# 运行
main "$@"
