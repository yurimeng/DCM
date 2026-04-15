#!/bin/bash
#
# DCM Node Agent 卸载脚本 (macOS)
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

INSTALL_DIR="${HOME}/.dcm-node-agent"

echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  DCM Node Agent 卸载程序${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# 检查安装目录
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${GREEN}DCM Node Agent 未安装${NC}"
    exit 0
fi

# 停止 Agent
if [ -f "${INSTALL_DIR}/agent.pid" ]; then
    PID=$(cat "${INSTALL_DIR}/agent.pid")
    if kill -0 $PID 2>/dev/null; then
        echo "停止 Agent (PID: $PID)..."
        kill $PID
    fi
fi

echo ""
read -p "是否删除所有数据? [y/N]: " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "删除安装目录: ${INSTALL_DIR}"
    rm -rf "${INSTALL_DIR}"
    echo -e "${GREEN}✅ 已删除${NC}"
else
    echo "保留配置文件: ${INSTALL_DIR}"
fi

echo ""
echo -e "${GREEN}卸载完成!${NC}"
