#!/bin/bash
#
# DCM Node Agent 一键安装脚本 (macOS)
# 
# 支持多网络协议: HTTPS, P2P, Relay
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 变量
INSTALL_DIR="${HOME}/.dcm-node-agent"
CONFIG_FILE="${INSTALL_DIR}/config.json"
LOG_FILE="${INSTALL_DIR}/agent.log"
PID_FILE="${INSTALL_DIR}/agent.pid"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  DCM Node Agent 安装脚本 (macOS)${NC}"
echo -e "${BLUE}  支持: HTTPS | P2P | Relay${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查 Python 3
check_python() {
    echo -e "${YELLOW}[1/6] 检查 Python 3...${NC}"
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
        echo -e "${GREEN}✅ Python ${PYTHON_VERSION} 已安装${NC}"
    else
        echo -e "${RED}❌ Python 3 未安装${NC}"
        echo "请先安装 Python 3: brew install python3"
        exit 1
    fi
}

# 检查 Homebrew
check_homebrew() {
    echo -e "${YELLOW}[2/6] 检查 Homebrew...${NC}"
    if command -v brew &> /dev/null; then
        echo -e "${GREEN}✅ Homebrew 已安装${NC}"
    else
        echo -e "${RED}❌ Homebrew 未安装${NC}"
        echo "请先安装 Homebrew: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        exit 1
    fi
}

# 检查 Ollama
check_ollama() {
    echo -e "${YELLOW}[3/6] 检查 Ollama...${NC}"
    
    # 检查 Ollama 是否运行
    if curl -s http://localhost:11434/api/tags &> /dev/null; then
        echo -e "${GREEN}✅ Ollama 正在运行${NC}"
        
        # 检查模型
        MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; m=json.load(sys.stdin); print(len(m.get('models',[])))" 2>/dev/null || echo "0")
        if [ "$MODELS" -gt 0 ]; then
            echo -e "${GREEN}✅ 已安装 ${MODELS} 个模型${NC}"
        else
            echo -e "${YELLOW}⚠️ Ollama 运行中但没有模型${NC}"
            echo "推荐安装: ollama pull qwen2.5:7b"
        fi
    else
        echo -e "${YELLOW}⚠️ Ollama 未运行${NC}"
        echo ""
        read -p "是否自动安装并启动 Ollama? [Y/n]: " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            # 安装 Ollama
            echo -e "${BLUE}安装 Ollama...${NC}"
            brew install ollama
            
            # 启动 Ollama
            echo -e "${BLUE}启动 Ollama...${NC}"
            brew services start ollama 2>/dev/null || ollama serve &
            
            # 等待 Ollama 启动
            echo -e "${BLUE}等待 Ollama 启动...${NC}"
            for i in {1..30}; do
                if curl -s http://localhost:11434/api/tags &> /dev/null; then
                    echo -e "${GREEN}✅ Ollama 已启动${NC}"
                    break
                fi
                sleep 1
            done
            
            # 拉取默认模型
            read -p "是否下载 qwen2.5:7b 模型? [Y/n]: " -n 1 -r
            echo ""
            if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                echo -e "${BLUE}下载模型中 (可能需要几分钟)...${NC}"
                ollama pull qwen2.5:7b
            fi
        fi
    fi
}

# 检查网络
check_network() {
    echo -e "${YELLOW}[4/6] 检查网络连接...${NC}"
    
    # 检查云端 API
    if curl -s --max-time 5 "https://dcm-api-p00a.onrender.com/health" &> /dev/null; then
        echo -e "${GREEN}✅ 云端 API 可达 (HTTPS)${NC}"
    else
        echo -e "${YELLOW}⚠️ 云端 API 不可达，Agent 将自动降级${NC}"
    fi
}

# 创建安装目录
create_dirs() {
    echo -e "${YELLOW}[5/6] 创建安装目录...${NC}"
    mkdir -p "${INSTALL_DIR}"
    mkdir -p "${INSTALL_DIR}/logs"
    echo -e "${GREEN}✅ 安装目录: ${INSTALL_DIR}${NC}"
}

# 配置 Agent
configure_agent() {
    echo -e "${YELLOW}[6/6] 配置 Agent...${NC}"
    
    # 读取或创建配置
    if [ -f "${CONFIG_FILE}" ]; then
        echo -e "${GREEN}✅ 使用现有配置${NC}"
    else
        # 创建默认配置
        cat > "${CONFIG_FILE}" << EOF
{
    "dcm_url": "https://dcm-api-p00a.onrender.com",
    "model": "qwen2.5:7b",
    "gpu_count": 1,
    "slot_count": 4,
    "worker_count": 2,
    "poll_interval": 3,
    "heartbeat_interval": 30,
    "stake_amount": 200.0,
    "network_enabled": true,
    "p2p_enabled": false,
    "relay_enabled": false
}
EOF
        echo -e "${GREEN}✅ 默认配置已创建${NC}"
    fi
    
    # 创建启动脚本
    cat > "${INSTALL_DIR}/start.sh" << 'STARTSCRIPT'
#!/bin/bash
cd "$(dirname "$0")"
nohup python3 -m src.node_agent >> logs/agent.log 2>&1 &
echo $! > agent.pid
echo "Agent 已启动 (PID: $(cat agent.pid))"
echo "网络协议: HTTPS (支持 P2P/Relay 自动降级)"
STARTSCRIPT
    chmod +x "${INSTALL_DIR}/start.sh"
    
    # 创建停止脚本
    cat > "${INSTALL_DIR}/stop.sh" << 'STOPSCRIPT'
#!/bin/bash
if [ -f agent.pid ]; then
    PID=$(cat agent.pid)
    if kill -0 $PID 2>/dev/null; then
        kill $PID
        echo "Agent 已停止 (PID: $PID)"
    else
        echo "Agent 未运行"
    fi
    rm -f agent.pid
else
    echo "Agent 未运行"
fi
STOPSCRIPT
    chmod +x "${INSTALL_DIR}/stop.sh"
    
    # 创建状态脚本
    cat > "${INSTALL_DIR}/status.sh" << 'STATUSSCRIPT'
#!/bin/bash
if [ -f agent.pid ]; then
    PID=$(cat agent.pid)
    if kill -0 $PID 2>/dev/null; then
        echo "Agent 运行中 (PID: $PID)"
        exit 0
    fi
fi
echo "Agent 未运行"
exit 1
STATUSSCRIPT
    chmod +x "${INSTALL_DIR}/status.sh"
    
    echo -e "${GREEN}✅ 启动脚本已创建${NC}"
}

# 启动 Agent
start_agent() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  安装完成!${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo "安装目录: ${INSTALL_DIR}"
    echo ""
    echo "使用方法:"
    echo "  ${INSTALL_DIR}/start.sh   # 启动 Agent"
    echo "  ${INSTALL_DIR}/stop.sh    # 停止 Agent"
    echo "  ${INSTALL_DIR}/status.sh  # 查看状态"
    echo "  tail -f ${INSTALL_DIR}/logs/agent.log  # 查看日志"
    echo ""
    
    read -p "是否立即启动 Agent? [Y/n]: " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        cd "${INSTALL_DIR}"
        source start.sh
        echo ""
        echo "查看日志: tail -f ${INSTALL_DIR}/logs/agent.log"
    fi
}

# 主流程
main() {
    check_python
    check_homebrew
    check_ollama
    check_network
    create_dirs
    configure_agent
    start_agent
}

main "$@"
