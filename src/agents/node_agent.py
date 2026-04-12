"""
Node Agent SDK - 节点客户端
来源: F2-NodeAgent-Spec.md
"""

import json
import hashlib
import time
import threading
import logging
from enum import Enum
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

import requests
import websocket

from config import settings

logger = logging.getLogger(__name__)


class NodeStatus(str, Enum):
    """Node Agent 状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    IDLE = "idle"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class Job:
    """Job 数据结构"""
    job_id: str
    model: str
    input_tokens: int
    output_tokens_limit: int
    max_latency: int
    locked_price: float
    input_text: str = ""  # 解码后的输入
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Job":
        return cls(
            job_id=data["job_id"],
            model=data["model"],
            input_tokens=data["input_tokens"],
            output_tokens_limit=data["output_tokens_limit"],
            max_latency=data["max_latency"],
            locked_price=data["locked_price"],
        )


@dataclass
class JobResult:
    """Job 执行结果"""
    job_id: str
    result: str
    result_hash: str
    actual_latency_ms: int
    actual_output_tokens: int


@dataclass
class NodeConfig:
    """Node Agent 配置"""
    router_host: str = "localhost"
    router_port: int = 8000
    use_websocket: bool = True
    poll_interval: int = 5
    reconnect_interval: int = 10
    max_retries: int = 3
    
    ollama_host: str = "localhost"
    ollama_port: int = 11434
    ollama_model: str = "llama3-8b"
    ollama_timeout: int = 60
    
    node_id: str = ""
    heartbeat_interval: int = 30
    max_concurrent_jobs: int = 1
    
    @property
    def router_url(self) -> str:
        return f"http://{self.router_host}:{self.router_port}"
    
    @property
    def websocket_url(self) -> str:
        return f"ws://{self.router_host}:{self.router_port}/ws/nodes/{self.node_id}"
    
    @property
    def ollama_url(self) -> str:
        return f"http://{self.ollama_host}:{self.ollama_port}"


class OllamaClient:
    """Ollama API 客户端"""
    
    def __init__(self, config: NodeConfig):
        self.config = config
        self.url = config.ollama_url
    
    def generate(self, prompt: str, max_tokens: int, timeout: int = None) -> Dict:
        """
        调用 Ollama 生成文本
        
        Returns:
            {
                "response": str,
                "done": bool,
                "total_duration": int,  # nanoseconds
                "eval_count": int  # output token count
            }
        """
        timeout = timeout or self.config.ollama_timeout
        
        payload = {
            "model": self.config.ollama_model,
            "prompt": prompt,
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.7,
            },
            "stream": False,
        }
        
        response = requests.post(
            f"{self.url}/api/generate",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    
    def is_available(self) -> bool:
        """检查 Ollama 是否可用"""
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False


class NodeAgent:
    """Node Agent 主类"""
    
    def __init__(self, config: NodeConfig, node_id: str):
        self.config = config
        self.node_id = node_id
        self.status = NodeStatus.DISCONNECTED
        
        self.ollama = OllamaClient(config)
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        
        self.current_job: Optional[Job] = None
        self.running = False
        
        # 心跳
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_heartbeat = threading.Event()
        
        # 回调
        self.on_job_received: Optional[Callable[[Job], None]] = None
        self.on_status_change: Optional[Callable[[NodeStatus], None]] = None
        self.on_error: Optional[Callable[[str, Exception], None]] = None
    
    # ===== 连接管理 =====
    
    def connect(self) -> bool:
        """连接到 Router"""
        self._set_status(NodeStatus.CONNECTING)
        
        if self.config.use_websocket:
            return self._connect_websocket()
        else:
            return self._connect_polling()
    
    def _connect_websocket(self) -> bool:
        """WebSocket 连接"""
        try:
            self.ws = websocket.WebSocketApp(
                self.config.websocket_url,
                on_open=self._on_ws_open,
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close,
            )
            
            self.ws_thread = threading.Thread(
                target=self.ws.run_forever,
                daemon=True,
            )
            self.ws_thread.start()
            
            # 等待连接建立（5秒超时）
            for _ in range(50):
                if self.status == NodeStatus.IDLE:
                    return True
                time.sleep(0.1)
            
            return self.status == NodeStatus.IDLE
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self._set_status(NodeStatus.DISCONNECTED)
            return False
    
    def _connect_polling(self) -> bool:
        """HTTP Polling 连接"""
        try:
            # 确认节点上线
            response = requests.post(
                f"{self.config.router_url}/api/v1/nodes/{self.node_id}/online",
                timeout=10,
            )
            
            if response.status_code == 200:
                self._set_status(NodeStatus.IDLE)
                self._start_heartbeat()
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Polling connection failed: {e}")
            self._set_status(NodeStatus.DISCONNECTED)
            return False
    
    def disconnect(self):
        """断开连接"""
        self.running = False
        self._stop_heartbeat.set()
        
        if self.ws:
            self.ws.close()
        
        self._set_status(NodeStatus.DISCONNECTED)
    
    # ===== WebSocket 回调 =====
    
    def _on_ws_open(self, ws):
        """WebSocket 连接打开"""
        logger.info("WebSocket connected")
        
        # 发送注册消息
        self._send_ws_message({
            "type": "register",
            "node_id": self.node_id,
            "capabilities": {
                "models": [self.config.ollama_model],
                "max_concurrent": self.config.max_concurrent_jobs,
            }
        })
    
    def _on_ws_message(self, ws, message: str):
        """收到 WebSocket 消息"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "ack":
                # 注册确认
                self._set_status(NodeStatus.IDLE)
                self._start_heartbeat()
                logger.info("Registered with Router")
                
            elif msg_type == "job_assigned":
                # 收到 Job
                job = Job.from_dict(data["job"])
                self._handle_job(job)
                
            elif msg_type == "heartbeat_ack":
                # 心跳确认
                logger.debug("Heartbeat acknowledged")
                
            elif msg_type == "error":
                # 错误消息
                error_msg = data.get("message", "Unknown error")
                logger.error(f"Router error: {error_msg}")
                if self.on_error:
                    self.on_error(error_msg, None)
                    
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    def _on_ws_error(self, ws, error):
        """WebSocket 错误"""
        logger.error(f"WebSocket error: {error}")
        if self.on_error:
            self.on_error(str(error), error)
    
    def _on_ws_close(self, ws, close_status_code, close_msg):
        """WebSocket 关闭"""
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self._set_status(NodeStatus.DISCONNECTED)
        
        # 自动重连
        if self.running:
            self._schedule_reconnect()
    
    def _send_ws_message(self, data: Dict):
        """发送 WebSocket 消息"""
        if self.ws:
            self.ws.send(json.dumps(data))
    
    # ===== 心跳 =====
    
    def _start_heartbeat(self):
        """启动心跳"""
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
        )
        self._heartbeat_thread.start()
    
    def _heartbeat_loop(self):
        """心跳循环"""
        while not self._stop_heartbeat.is_set():
            try:
                if self.config.use_websocket:
                    self._send_ws_message({
                        "type": "heartbeat",
                        "node_id": self.node_id,
                        "status": "processing" if self.current_job else "idle",
                        "current_job_id": self.current_job.job_id if self.current_job else None,
                        "timestamp": int(time.time() * 1000),
                    })
                else:
                    # HTTP Polling 模式的心跳
                    requests.post(
                        f"{self.config.router_url}/api/v1/nodes/{self.node_id}/heartbeat",
                        json={
                            "status": "processing" if self.current_job else "idle",
                            "current_job_id": self.current_job.job_id if self.current_job else None,
                        },
                        timeout=5,
                    )
                
                self._stop_heartbeat.wait(self.config.heartbeat_interval)
                
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
    
    # ===== Job 处理 =====
    
    def _handle_job(self, job: Job):
        """处理收到的 Job"""
        logger.info(f"Received job: {job.job_id}")
        self.current_job = job
        self._set_status(NodeStatus.PROCESSING)
        
        if self.on_job_received:
            self.on_job_received(job)
        
        # 在后台执行
        thread = threading.Thread(
            target=self._execute_job,
            args=(job,),
            daemon=True,
        )
        thread.start()
    
    def _execute_job(self, job: Job):
        """执行 Job"""
        start_time = time.time()
        
        try:
            # 1. 解码输入（base64 → UTF-8）
            # MVP 简化：假设输入是明文
            input_text = job.input_text or f"Input tokens: {job.input_tokens}"
            
            # 2. 调用 Ollama
            result = self.ollama.generate(
                prompt=input_text,
                max_tokens=job.output_tokens_limit,
                timeout=job.max_latency // 1000 + 10,  # 延迟限制 + buffer
            )
            
            # 3. 提取结果
            output_text = result.get("response", "")
            actual_latency_ms = int(result.get("total_duration", 0) / 1_000_000)
            actual_output_tokens = result.get("eval_count", self._estimate_tokens(output_text))
            
            # 4. 计算哈希
            result_hash = hashlib.sha256(output_text.encode()).hexdigest()
            
            # 5. 提交结果
            self._submit_result(
                job=job,
                result=output_text,
                result_hash=result_hash,
                actual_latency_ms=actual_latency_ms,
                actual_output_tokens=actual_output_tokens,
            )
            
            self._set_status(NodeStatus.COMPLETED)
            
        except Exception as e:
            logger.error(f"Job execution failed: {e}")
            self._handle_job_error(job, str(e))
        
        finally:
            self.current_job = None
    
    def _submit_result(self, job: Job, result: str, result_hash: str,
                       actual_latency_ms: int, actual_output_tokens: int):
        """提交 Job 结果"""
        # base64 编码（实际应使用 base64）
        import base64
        encoded_result = base64.b64encode(result.encode()).decode()
        
        payload = {
            "result": encoded_result,
            "result_hash": result_hash,
            "actual_latency_ms": actual_latency_ms,
            "actual_output_tokens": actual_output_tokens,
        }
        
        # 重试机制
        for attempt in range(self.config.max_retries):
            try:
                response = requests.post(
                    f"{self.config.router_url}/api/v1/nodes/{self.node_id}/jobs/{job.job_id}/result",
                    json=payload,
                    timeout=10,
                )
                
                if response.status_code == 200:
                    logger.info(f"Result submitted for job: {job.job_id}")
                    return
                    
            except Exception as e:
                logger.warning(f"Submit attempt {attempt + 1} failed: {e}")
                time.sleep(5)
        
        logger.error(f"Failed to submit result after {self.config.max_retries} attempts")
    
    def _handle_job_error(self, job: Job, error_message: str):
        """处理 Job 执行错误"""
        # 提交错误状态
        payload = {
            "error_type": "execution_error",
            "error_message": error_message,
        }
        
        try:
            requests.post(
                f"{self.config.router_url}/api/v1/nodes/{self.node_id}/jobs/{job.job_id}/error",
                json=payload,
                timeout=10,
            )
        except Exception as e:
            logger.error(f"Failed to report error: {e}")
        
        self._set_status(NodeStatus.ERROR)
    
    # ===== HTTP Polling 模式 =====
    
    def _poll_loop(self):
        """轮询循环（HTTP 模式）"""
        while self.running:
            try:
                response = requests.post(
                    f"{self.config.router_url}/api/v1/nodes/{self.node_id}/poll",
                    timeout=self.config.poll_interval,
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get("has_job"):
                        job = Job.from_dict(data["job"])
                        self._handle_job(job)
                
            except Exception as e:
                logger.error(f"Poll failed: {e}")
            
            time.sleep(self.config.poll_interval)
    
    # ===== 辅助方法 =====
    
    def _set_status(self, status: NodeStatus):
        """设置状态"""
        if self.status != status:
            self.status = status
            logger.info(f"Node status: {status.value}")
            if self.on_status_change:
                self.on_status_change(status)
    
    def _schedule_reconnect(self):
        """调度重连"""
        def reconnect():
            time.sleep(self.config.reconnect_interval)
            if self.running:
                self.connect()
        
        thread = threading.Thread(target=reconnect, daemon=True)
        thread.start()
    
    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """估算 token 数量（简化版）"""
        return len(text.encode('utf-8')) // 4
    
    # ===== 公开方法 =====
    
    def start(self):
        """启动 Node Agent"""
        self.running = True
        
        if not self.connect():
            raise RuntimeError("Failed to connect to Router")
        
        if not self.config.use_websocket:
            # 启动轮询线程
            self.ws_thread = threading.Thread(
                target=self._poll_loop,
                daemon=True,
            )
            self.ws_thread.start()
    
    def stop(self):
        """停止 Node Agent"""
        self.disconnect()
        logger.info("Node Agent stopped")
    
    def wait(self):
        """等待运行"""
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()


def create_node_agent(
    router_host: str = "localhost",
    router_port: int = 8000,
    node_id: str = "",
    use_websocket: bool = True,
) -> NodeAgent:
    """创建 Node Agent 实例"""
    config = NodeConfig(
        router_host=router_host,
        router_port=router_port,
        node_id=node_id,
        use_websocket=use_websocket,
    )
    return NodeAgent(config, node_id)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="DCM Node Agent")
    parser.add_argument("--node-id", required=True, help="Node ID")
    parser.add_argument("--router-host", default="localhost", help="Router host")
    parser.add_argument("--router-port", type=int, default=8000, help="Router port")
    parser.add_argument("--no-websocket", action="store_true", help="Use HTTP polling")
    
    args = parser.parse_args()
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # 创建并启动 Agent
    agent = create_node_agent(
        router_host=args.router_host,
        router_port=args.router_port,
        node_id=args.node_id,
        use_websocket=not args.no_websocket,
    )
    
    agent.start()
    agent.wait()
