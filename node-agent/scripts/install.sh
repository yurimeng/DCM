#!/bin/bash
#
# DCM Node Agent 一键安装脚本 (macOS)
#
# 特性:
# - 交互式用户配置
# - Python 路径自动检测
# - Ollama 自动安装
# - 用户注册/登录
#

set -e

# ═══════════════════════════════════════════════════════════════
# 颜色定义
# ═══════════════════════════════════════════════════════════════
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# ═══════════════════════════════════════════════════════════════
# 变量定义
# ═══════════════════════════════════════════════════════════════
INSTALL_DIR="${HOME}/.dcm-node-agent"
CONFIG_FILE="${INSTALL_DIR}/config.json"
LOG_FILE="${INSTALL_DIR}/logs/agent.log"
PID_FILE="${INSTALL_DIR}/agent.pid"
VENV_DIR="${INSTALL_DIR}/venv"

# 默认 DCM URL
DEFAULT_DCM_URL="https://dcm-api-p00a.onrender.com"

# Python 路径检测
detect_python() {
    # 优先级: venv > brew > anaconda > 系统 python3 > python
    if [ -d "${VENV_DIR}/bin" ]; then
        PYTHON="${VENV_DIR}/bin/python3"
        PIP="${VENV_DIR}/bin/pip3"
    elif command -v /usr/local/bin/python3 &> /dev/null; then
        PYTHON="/usr/local/bin/python3"
        PIP="/usr/local/bin/pip3"
    elif command -v /opt/homebrew/bin/python3 &> /dev/null; then
        PYTHON="/opt/homebrew/bin/python3"
        PIP="/opt/homebrew/bin/pip3"
    elif command -v python3 &> /dev/null; then
        PYTHON="python3"
        PIP="pip3"
    elif command -v python &> /dev/null; then
        PYTHON="python"
        PIP="pip"
    else
        PYTHON=""
        PIP=""
    fi
}

# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

ask() {
    local prompt="$1"
    local default="$2"
    local result
    
    if [ -n "$default" ]; then
        read -p "$prompt [$default]: " result
        echo "${result:-$default}"
    else
        read -p "$prompt: " result
        echo "$result"
    fi
}

ask_password() {
    local prompt="$1"
    local result
    
    while true; do
        read -s -p "$prompt: " result
        echo ""
        if [ -z "$result" ]; then
            log_warn "密码不能为空"
            continue
        fi
        
        local confirm
        read -s -p "确认密码: " confirm
        echo ""
        
        if [ "$result" != "$confirm" ]; then
            log_warn "密码不匹配，请重新输入"
            continue
        fi
        break
    done
    
    echo "$result"
}

ask_choice() {
    local prompt="$1"
    local default="$2"
    local options="$3"
    
    echo ""
    echo "$prompt"
    PS3="请选择 (默认: $default): "
    
    select opt in $options; do
        if [ -z "$opt" ]; then
            echo "$default"
            break
        fi
        echo "$opt"
        break
    done
}

# ═══════════════════════════════════════════════════════════════
# 欢迎界面
# ═══════════════════════════════════════════════════════════════
show_banner() {
    clear
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║                                                          ║"
    echo "║              DCM Node Agent 安装程序                       ║"
    echo "║              Decentralized Compute Market                 ║"
    echo "║                                                          ║"
    echo "║              版本: v3.2.0 (macOS)                       ║"
    echo "║                                                          ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
# 检查环境
# ═══════════════════════════════════════════════════════════════
check_environment() {
    log_step "1. 检测运行环境..."
    
    # Python 检测
    detect_python
    if [ -z "$PYTHON" ]; then
        log_error "未找到 Python 3"
        echo ""
        echo "请先安装 Python:"
        echo "  brew install python3"
        echo ""
        exit 1
    fi
    
    PYTHON_VERSION=$($PYTHON --version 2>&1 | cut -d' ' -f2)
    log_info "Python: ${PYTHON} (${PYTHON_VERSION})"
    
    # 检查 Python 版本 >= 3.8
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
        log_error "Python 版本需要 >= 3.8，当前版本: ${PYTHON_VERSION}"
        exit 1
    fi
    
    # Homebrew 检测
    if command -v brew &> /dev/null; then
        log_info "Homebrew: 已安装"
    else
        log_warn "Homebrew 未安装 (可选)"
    fi
    
    echo ""
}

# ═══════════════════════════════════════════════════════════════
# 用户配置
# ═══════════════════════════════════════════════════════════════
configure_user() {
    log_step "2. 用户配置..."
    echo ""
    echo "请提供以下信息 (这些信息将用于创建您的账户):"
    echo ""
    
    # 用户名
    while true; do
        USERNAME=$(ask "用户名 (字母/数字/下划线, 3-20字符)" "")
        if [[ "$USERNAME" =~ ^[a-zA-Z0-9_]{3,20}$ ]]; then
            break
        fi
        log_error "用户名格式错误，请使用 3-20 位字母/数字/下划线"
    done
    
    # 邮箱
    while true; do
        EMAIL=$(ask "邮箱地址" "")
        if [[ "$EMAIL" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
            break
        fi
        log_error "邮箱格式错误"
    done
    
    # 密码
    PASSWORD=$(ask_password "设置密码 (至少 8 字符)")
    while [ ${#PASSWORD} -lt 8 ]; do
        log_error "密码至少需要 8 字符"
        PASSWORD=$(ask_password "设置密码 (至少 8 字符)")
    done
    
    echo ""
    log_info "用户: ${USERNAME}"
    log_info "邮箱: ${EMAIL}"
    
    # 确认信息
    echo ""
    read -p "确认以上信息? [Y/n]: " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        configure_user
    fi
    
    echo ""
}

# ═══════════════════════════════════════════════════════════════
# 节点配置
# ═══════════════════════════════════════════════════════════════
configure_node() {
    log_step "3. 节点配置..."
    
    # DCM URL
    DCM_URL=$(ask "DCM API 地址" "$DEFAULT_DCM_URL")
    
    # 模型选择
    echo ""
    echo "选择要运行的模型:"
    echo "  1. qwen2.5:7b (推荐, 4.7GB)"
    echo "  2. qwen2.5:14b (更大, 9GB)"
    echo "  3. llama3:8b (8GB)"
    echo "  4. 自定义"
    
    read -p "请选择 [1]: " MODEL_CHOICE
    MODEL_CHOICE=${MODEL_CHOICE:-1}
    
    case $MODEL_CHOICE in
        1) MODEL="qwen2.5:7b" ;;
        2) MODEL="qwen2.5:14b" ;;
        3) MODEL="llama3:8b" ;;
        4) MODEL=$(ask "输入模型名称" "qwen2.5:7b") ;;
        *) MODEL="qwen2.5:7b" ;;
    esac
    
    # GPU 数量
    GPU_COUNT=$(ask "GPU 数量 (1-N)" "1")
    GPU_COUNT=${GPU_COUNT:-1}
    
    # Worker 数量
    WORKER_COUNT=$(ask "Worker 数量 (建议: GPU数量 x 2)" "$((GPU_COUNT * 2))")
    WORKER_COUNT=${WORKER_COUNT:-$((GPU_COUNT * 2))}
    
    # Slot 数量
    SLOT_COUNT=$(ask "Slot 数量 (并发任务数)" "$((WORKER_COUNT * 2))")
    SLOT_COUNT=${SLOT_COUNT:-$((WORKER_COUNT * 2))}
    
    # 轮询间隔
    POLL_INTERVAL=$(ask "Job 轮询间隔 (秒)" "3")
    POLL_INTERVAL=${POLL_INTERVAL:-3}
    
    # 质押金额
    STAKE_AMOUNT=$(ask "质押金额 (USDC)" "50")
    STAKE_AMOUNT=${STAKE_AMOUNT:-50}
    
    echo ""
    log_info "DCM URL: ${DCM_URL}"
    log_info "模型: ${MODEL}"
    log_info "GPU: ${GPU_COUNT}, Worker: ${WORKER_COUNT}, Slot: ${SLOT_COUNT}"
    log_info "轮询间隔: ${POLL_INTERVAL}秒"
    log_info "质押金额: ${STAKE_AMOUNT} USDC"
    
    echo ""
}

# ═══════════════════════════════════════════════════════════════
# 检查/安装 Ollama
# ═══════════════════════════════════════════════════════════════
setup_ollama() {
    log_step "4. Ollama 配置..."
    
    # 检查 Ollama
    if curl -s --max-time 3 http://localhost:11434/api/tags &> /dev/null; then
        log_info "Ollama: 已运行"
        
        # 检查模型
        MODELS=$(curl -s http://localhost:11434/api/tags 2>/dev/null | $PYTHON -c "import sys,json; m=json.load(sys.stdin); print([x['name'] for x in m.get('models',[])])" 2>/dev/null || echo "[]")
        
        if echo "$MODELS" | grep -q "$MODEL"; then
            log_info "模型 ${MODEL}: 已安装"
        else
            echo ""
            read -p "是否下载 ${MODEL} 模型? [Y/n]: " -n 1 -r
            echo ""
            if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                log_info "正在下载模型 (可能需要几分钟)..."
                $PYTHON -m ollama pull $MODEL 2>/dev/null || ollama pull $MODEL
                log_info "模型下载完成"
            fi
        fi
    else
        echo ""
        log_warn "Ollama 未运行"
        echo ""
        read -p "是否安装并启动 Ollama? [Y/n]: " -n 1 -r
        echo ""
        
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            if command -v brew &> /dev/null; then
                log_info "安装 Ollama..."
                brew install ollama
                
                log_info "启动 Ollama..."
                brew services start ollama 2>/dev/null || ollama serve &
                
                # 等待启动
                log_info "等待 Ollama 启动..."
                for i in {1..30}; do
                    if curl -s --max-time 2 http://localhost:11434/api/tags &> /dev/null; then
                        log_info "Ollama 已启动"
                        break
                    fi
                    sleep 1
                done
                
                # 下载模型
                echo ""
                read -p "是否下载 ${MODEL} 模型? [Y/n]: " -n 1 -r
                echo ""
                if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                    log_info "正在下载模型..."
                    ollama pull $MODEL
                    log_info "模型下载完成"
                fi
            else
                log_error "请先安装 Homebrew 或手动安装 Ollama"
                echo "访问: https://ollama.ai"
            fi
        fi
    fi
    
    echo ""
}

# ═══════════════════════════════════════════════════════════════
# 创建虚拟环境并安装依赖
# ═══════════════════════════════════════════════════════════════
setup_python() {
    log_step "5. Python 环境配置..."
    
    # 创建安装目录
    mkdir -p "${INSTALL_DIR}/logs"
    log_info "安装目录: ${INSTALL_DIR}"
    
    # 检查是否已有虚拟环境
    if [ ! -d "${VENV_DIR}" ]; then
        log_info "创建虚拟环境..."
        $PYTHON -m venv "${VENV_DIR}"
        log_info "虚拟环境已创建"
    else
        log_info "使用现有虚拟环境"
    fi
    
    # 激活虚拟环境
    source "${VENV_DIR}/bin/activate"
    
    # 升级 pip
    log_info "升级 pip..."
    pip install --upgrade pip -q
    
    # 安装依赖
    log_info "安装 Python 依赖..."
    pip install requests ollama -q
    
    echo ""
}

# ═══════════════════════════════════════════════════════════════
# 注册/登录用户
# ═══════════════════════════════════════════════════════════════
register_user() {
    log_step "6. 用户注册..."
    
    # 创建临时脚本用于 API 调用
    REGISTER_SCRIPT="${INSTALL_DIR}/.register_temp.py"
    
    cat > "$REGISTER_SCRIPT" << 'PYTHON_EOF'
import sys
import json
import requests

def main():
    DCM_URL = sys.argv[1]
    username = sys.argv[2]
    email = sys.argv[3]
    password = sys.argv[4]
    
    try:
        # 注册
        resp = requests.post(
            f"{DCM_URL}/api/v1/users/register",
            json={
                "username": username,
                "email": email,
                "password": password,
            },
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            print(json.dumps({"success": True, "user_id": data.get("user_id", "")}))
        elif resp.status_code == 409:
            # 用户已存在，尝试登录
            resp = requests.post(
                f"{DCM_URL}/api/v1/users/login",
                json={"username": username, "password": password},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                print(json.dumps({"success": True, "user_id": data.get("user_id", "")}))
            else:
                print(json.dumps({"success": False, "error": "登录失败"}))
        else:
            print(json.dumps({"success": False, "error": resp.text}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

if __name__ == "__main__":
    main()
PYTHON_EOF
    
    # 执行注册
    source "${VENV_DIR}/bin/activate"
    RESULT=$($PYTHON "$REGISTER_SCRIPT" "$DCM_URL" "$USERNAME" "$EMAIL" "$PASSWORD")
    rm -f "$REGISTER_SCRIPT"
    
    # 解析结果
    USER_ID=$(echo "$RESULT" | $PYTHON -c "import sys,json; print(json.load(sys.stdin).get('user_id', ''))" 2>/dev/null)
    
    if [ -n "$USER_ID" ]; then
        log_info "用户注册成功! User ID: ${USER_ID}"
    else
        ERROR=$(echo "$RESULT" | $PYTHON -c "import sys,json; print(json.load(sys.stdin).get('error', '未知错误'))" 2>/dev/null)
        log_error "用户注册失败: ${ERROR}"
        echo ""
        read -p "是否重试? [Y/n]: " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            register_user
        fi
    fi
    
    echo ""
}

# ═══════════════════════════════════════════════════════════════
# 创建配置文件
# ═══════════════════════════════════════════════════════════════
create_config() {
    log_step "7. 创建配置文件..."
    
    cat > "${CONFIG_FILE}" << EOF
{
    "user_id": "${USER_ID}",
    "username": "${USERNAME}",
    "email": "${EMAIL}",
    "dcm_url": "${DCM_URL}",
    "model": "${MODEL}",
    "gpu_count": ${GPU_COUNT},
    "slot_count": ${SLOT_COUNT},
    "worker_count": ${WORKER_COUNT},
    "poll_interval": ${POLL_INTERVAL},
    "heartbeat_interval": 30,
    "stake_amount": ${STAKE_AMOUNT},
    "network_enabled": true,
    "p2p_enabled": false,
    "relay_enabled": false,
    "ask_price": 0.000001,
    "avg_latency": 100,
    "region": "local"
}
EOF
    
    chmod 600 "${CONFIG_FILE}"
    log_info "配置文件: ${CONFIG_FILE}"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
# 创建管理脚本
# ═══════════════════════════════════════════════════════════════
create_scripts() {
    log_step "8. 创建管理脚本..."
    
    # 启动脚本
    cat > "${INSTALL_DIR}/start.sh" << 'STARTSCRIPT'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 激活虚拟环境
source venv/bin/activate

# 启动 Agent
nohup python3 -m src.node_agent >> logs/agent.log 2>&1 &
PID=$!

echo $PID > agent.pid
echo "DCM Node Agent 已启动 (PID: $PID)"
echo "查看日志: tail -f ${SCRIPT_DIR}/logs/agent.log"
STARTSCRIPT
    chmod +x "${INSTALL_DIR}/start.sh"
    
    # 停止脚本
    cat > "${INSTALL_DIR}/stop.sh" << 'STOPSCRIPT'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f agent.pid ]; then
    PID=$(cat agent.pid)
    if kill -0 $PID 2>/dev/null; then
        kill $PID
        echo "DCM Node Agent 已停止 (PID: $PID)"
    else
        echo "Agent 未运行"
    fi
    rm -f agent.pid
else
    echo "Agent 未运行"
fi
STOPSCRIPT
    chmod +x "${INSTALL_DIR}/stop.sh"
    
    # 状态脚本
    cat > "${INSTALL_DIR}/status.sh" << 'STATUSSCRIPT'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f agent.pid ]; then
    PID=$(cat agent.pid)
    if kill -0 $PID 2>/dev/null; then
        echo "DCM Node Agent 运行中 (PID: $PID)"
        echo ""
        echo "最近日志:"
        tail -5 logs/agent.log 2>/dev/null || echo "无日志"
        exit 0
    fi
fi
echo "DCM Node Agent 未运行"
exit 1
STATUSSCRIPT
    chmod +x "${INSTALL_DIR}/status.sh"
    
    # 重启脚本
    cat > "${INSTALL_DIR}/restart.sh" << 'RESTARTSCRIPT'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/stop.sh"
sleep 2
"$SCRIPT_DIR/start.sh"
RESTARTSCRIPT
    chmod +x "${INSTALL_DIR}/restart.sh"
    
    log_info "管理脚本已创建:"
    echo "  ${INSTALL_DIR}/start.sh   # 启动"
    echo "  ${INSTALL_DIR}/stop.sh    # 停止"
    echo "  ${INSTALL_DIR}/restart.sh # 重启"
    echo "  ${INSTALL_DIR}/status.sh  # 状态"
    echo ""
}

# ═══════════════════════════════════════════════════════════════
# 复制 Node Agent 代码
# ═══════════════════════════════════════════════════════════════
copy_code() {
    log_step "9. 部署 Node Agent..."
    
    # 获取当前脚本目录
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    SOURCE_DIR="$(dirname "$SCRIPT_DIR")"
    
    # 复制源码 (如果不是从源码运行)
    if [ "$SOURCE_DIR" != "$INSTALL_DIR" ] && [ -f "${SOURCE_DIR}/src/node_agent.py" ]; then
        cp -r "${SOURCE_DIR}/src" "${INSTALL_DIR}/"
        cp "${SOURCE_DIR}/run_node_agent.py" "${INSTALL_DIR}/"
        log_info "源码已复制到 ${INSTALL_DIR}"
    fi
    
    echo ""
}

# ═══════════════════════════════════════════════════════════════
# 完成安装
# ═══════════════════════════════════════════════════════════════
finish() {
    log_step "安装完成!"
    
    echo ""
    echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  安装成功!${NC}"
    echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "📁 安装目录: ${INSTALL_DIR}"
    echo "👤 用户: ${USERNAME}"
    echo "🔑 User ID: ${USER_ID}"
    echo "🤖 模型: ${MODEL}"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  管理命令:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ${INSTALL_DIR}/start.sh     启动 Agent"
    echo "  ${INSTALL_DIR}/stop.sh     停止 Agent"
    echo "  ${INSTALL_DIR}/restart.sh  重启 Agent"
    echo "  ${INSTALL_DIR}/status.sh   查看状态"
    echo ""
    echo "  查看日志:"
    echo "  tail -f ${INSTALL_DIR}/logs/agent.log"
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

# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════
main() {
    show_banner
    
    check_environment
    configure_user
    configure_node
    setup_ollama
    setup_python
    register_user
    create_config
    create_scripts
    copy_code
    finish
}

main "$@"
