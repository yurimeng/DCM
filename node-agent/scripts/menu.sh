#!/bin/bash
#
# DCM Node Agent 菜单脚本 (macOS)
#

set -e

INSTALL_DIR="${HOME}/.dcm-node-agent"
CONFIG_FILE="${INSTALL_DIR}/config.json"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 检查安装
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}DCM Node Agent 未安装${NC}"
    echo ""
    echo "运行安装脚本: ./install.sh"
    exit 1
fi

show_menu() {
    clear
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║           DCM Node Agent 管理菜单                        ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
    
    # 显示配置
    if [ -f "$CONFIG_FILE" ]; then
        echo -e "${BLUE}当前配置:${NC}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        grep -E '"username"|"model"|"dcm_url"' "$CONFIG_FILE" | sed 's/[[:space:]]*"//g' | sed 's/":.*/ /g' | sed 's/,//g'
        echo ""
    fi
    
    # Agent 状态
    if [ -f "${INSTALL_DIR}/agent.pid" ]; then
        PID=$(cat "${INSTALL_DIR}/agent.pid")
        if kill -0 $PID 2>/dev/null; then
            echo -e "${GREEN}🟢 Agent 运行中 (PID: $PID)${NC}"
        else
            echo -e "${RED}⚫ Agent 未运行${NC}"
        fi
    else
        echo -e "${RED}⚫ Agent 未运行${NC}"
    fi
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  1. 启动 Agent"
    echo "  2. 停止 Agent"
    echo "  3. 重启 Agent"
    echo "  4. 查看状态"
    echo "  5. 查看日志 (最后 50 行)"
    echo "  6. 实时日志 (Ctrl+C 退出)"
    echo "  7. 编辑配置"
    echo "  8. 卸载"
    echo "  0. 退出"
    echo ""
}

while true; do
    show_menu
    read -p "请选择: " choice
    
    case $choice in
        1)
            echo ""
            cd "${INSTALL_DIR}"
            source start.sh
            sleep 2
            ;;
        2)
            echo ""
            cd "${INSTALL_DIR}"
            source stop.sh
            ;;
        3)
            echo ""
            cd "${INSTALL_DIR}"
            source restart.sh
            ;;
        4)
            echo ""
            cd "${INSTALL_DIR}"
            source status.sh
            ;;
        5)
            echo ""
            if [ -f "${INSTALL_DIR}/logs/agent.log" ]; then
                tail -50 "${INSTALL_DIR}/logs/agent.log"
            else
                echo "无日志"
            fi
            echo ""
            read -p "按 Enter 继续..."
            ;;
        6)
            echo ""
            echo "按 Ctrl+C 退出"
            echo ""
            if [ -f "${INSTALL_DIR}/logs/agent.log" ]; then
                tail -f "${INSTALL_DIR}/logs/agent.log"
            else
                echo "无日志"
            fi
            ;;
        7)
            echo ""
            if command -v nano &> /dev/null; then
                nano "$CONFIG_FILE"
            elif command -v vim &> /dev/null; then
                vim "$CONFIG_FILE"
            else
                echo "请手动编辑: $CONFIG_FILE"
            fi
            ;;
        8)
            echo ""
            cd "$(dirname "$0")"
            ./uninstall.sh
            exit 0
            ;;
        0)
            echo ""
            echo "再见!"
            exit 0
            ;;
        *)
            echo ""
            echo "无效选择"
            ;;
    esac
    
    echo ""
    read -p "按 Enter 继续..."
done
