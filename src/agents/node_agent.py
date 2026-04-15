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
from typing import Optional, Callable, Dict, Any, List
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
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout: int = 60
    
    # Runtime 类型 (DCM v3.2)
    runtime_type: str = "ollama"  # ollama, vllm, llama.cpp
    
    node_id: str = ""
    user_id: str = ""  # 服务器所有者
    
    # Status Report 间隔 (DCM v3.2)
    capacity_report_interval: int = 30   # Node Capacity Report: 30-60秒
    live_status_interval: int = 3        # Node Live Status: 2-5秒
    
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
    """
    Ollama API 客户端 (DCM v3.2 保留兼容)
    
    推荐使用 Runtime Protocol:
    - src.models.runtime_protocol.OllamaAdapter
    """
    
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


class RuntimeClient:
    """
    Runtime 客户端 (DCM v3.2)
    
    统一的 Runtime 调用接口，支持多种推理后端:
    - Ollama
    - vLLM
    - llama.cpp
    
    使用 Runtime Protocol:
    - src.models.runtime_protocol.RuntimeRequest
    - src.models.runtime_protocol.RuntimeResponse
    """
    
    def __init__(self, config: NodeConfig):
        self.config = config
        self._adapter = None
        self._init_adapter()
    
    def _init_adapter(self):
        """初始化 Runtime 适配器"""
        from ..models.runtime_protocol import create_runtime_adapter
        
        runtime_type = getattr(self.config, 'runtime_type', 'ollama')
        
        self._adapter = create_runtime_adapter(
            runtime_type=runtime_type,
            host=self.config.ollama_host,
            port=self.config.ollama_port,
            timeout=self.config.ollama_timeout,
        )
    
    @property
    def adapter(self):
        """获取 Runtime 适配器"""
        return self._adapter
    
    def execute(self, request) -> 'RuntimeResponse':
        """
        执行 Runtime 请求
        
        Args:
            request: RuntimeRequest 对象
            
        Returns:
            RuntimeResponse 对象
        """
        if self._adapter is None:
            self._init_adapter()
        
        return self._adapter.generate(request)
    
    def is_available(self) -> bool:
        """检查 Runtime 是否可用"""
        if self._adapter is None:
            self._init_adapter()
        return self._adapter.is_available()
    
    def list_models(self) -> List[str]:
        """列出可用模型"""
        if self._adapter is None:
            self._init_adapter()
        return self._adapter.list_models()


class NodeAgent:
    """Node Agent 主类"""
    
    def __init__(self, config: NodeConfig, node_id: str):
        self.config = config
        self.node_id = node_id
        self.status = NodeStatus.DISCONNECTED
        
        # Runtime 客户端 (DCM v3.2 新增)
        self.ollama = OllamaClient(config)  # 保留兼容
        self.runtime = RuntimeClient(config)  # 新的统一接口
        
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        
        self.current_job: Optional[Job] = None
        self.running = False
        
        # 本地 Node 信息 (用于 Cluster 分配)
        self._node: Optional[Dict] = None
        self._current_cluster_id: Optional[str] = None
        
        # 心跳
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_heartbeat = threading.Event()
        
        # GPU 监控
        self._gpu_monitor = None
        self._init_gpu_monitor()
        
        # 回调
        self.on_job_received: Optional[Callable[[Job], None]] = None
        self.on_status_change: Optional[Callable[[NodeStatus], None]] = None
        self.on_error: Optional[Callable[[str, Exception], None]] = None
    
    # ===== Cluster 分配 =====
    
    def _init_node_info(self) -> Dict:
        """初始化本地 Node 信息
        
        注意: cluster_id 由 NodeStatusStore 生成，这里只记录本地信息
        """
        # 构建初始 Node 信息
        self._node = {
            "node_id": self.node_id,
            "user_id": self.config.user_id,
            "region": "unknown",  # TODO: 从 system_info 获取
            "stake_tier": "personal",  # 用户可配置
            "loaded_models": [self.config.ollama_model],
            "quality_score": 0.9,
            "success_rate": 0.95,
        }
        
        # cluster_id 由 NodeStatusStore 返回，Node 只做记录
        self._current_cluster_id = None
        
        return self._node
    
    def _check_and_update_cluster(self) -> Optional[str]:
        """
        检查并更新 Cluster ID
        
        流程:
        1. Node 发送 capacity_report 到 API
        2. NodeStatusStore 生成 cluster_id
        3. API 返回 new_cluster_id 给 Node
        4. Node 记录返回的 cluster_id
        
        Returns:
            None (cluster_id 由服务端生成)
        """
        # 更新本地 loaded_models
        if self._node is None:
            self._init_node_info()
        
        loaded_models = self._get_loaded_models()
        self._node["loaded_models"] = loaded_models
        
        # cluster_id 由 NodeStatusStore 返回，这里不做处理
        return None
    
    def get_current_cluster_id(self) -> Optional[str]:
        """获取当前 Cluster ID"""
        return self._current_cluster_id
    
    def set_cluster_id(self, cluster_id: str) -> None:
        """设置 Cluster ID (由 NodeStatusStore 返回)"""
        if self._current_cluster_id != cluster_id:
            old = self._current_cluster_id
            self._current_cluster_id = cluster_id
            logger.info(f"Cluster ID updated: {old} -> {cluster_id}")
    
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
    
    # ===== Status Report (DCM v3.2) =====
    
    def _start_status_reporting(self):
        """启动状态报告"""
        self._stop_heartbeat.clear()
        self._report_thread = threading.Thread(
            target=self._status_report_loop,
            daemon=True,
        )
        self._report_thread.start()
    
    def _status_report_loop(self):
        """状态报告循环 (DCM v3.2)
        
        发送两种报告:
        1. Node Capacity Report (低频/稳态) - 30-60秒
        2. Node Live Status Report (高频/调度) - 2-5秒
        """
        import time
        last_capacity_report = 0
        
        while not self._stop_heartbeat.is_set():
            try:
                timestamp = int(time.time() * 1000)
                
                # ===== Node Live Status Report (高频/调度) =====
                self._send_live_status_report(timestamp)
                
                # ===== Node Capacity Report (低频/稳态) =====
                if timestamp - last_capacity_report >= self.config.capacity_report_interval * 1000:
                    self._send_capacity_report(timestamp)
                    last_capacity_report = timestamp
                
                self._stop_heartbeat.wait(self.config.live_status_interval)
                
            except Exception as e:
                logger.error(f"Status report failed: {e}")
    
    def _send_live_status_report(self, timestamp: int):
        """发送 Node Live Status Report (高频/调度)
        
        频率: 2-5 秒
        """
        vram_used = self._get_vram_usage()
        vram_total = self._get_vram_total()
        
        report = {
            "type": "node_live_status",
            "node_id": self.node_id,
            "timestamp": timestamp,
            "status": {
                "vram_used_gb": vram_used,
                "vram_total_gb": vram_total,
            },
            "capacity": {
                "max_concurrency_available": self._calculate_available_concurrency(),
            },
            "load": {
                "active_jobs": len([j for j in [self.current_job] if j]),
                "available_token_capacity": self._calculate_available_token_capacity(),
            },
        }
        
        if self.config.use_websocket:
            self._send_ws_message(report)
        else:
            requests.post(
                f"{self.config.router_url}/api/v1/nodes/{self.node_id}/live_status",
                json=report,
                timeout=5,
            )
    
    def _send_capacity_report(self, timestamp: int):
        """发送 Node Capacity Report (低频/稳态)
        
        频率: 30-60 秒
        
        流程:
        1. 发送 capacity_report 到 API
        2. API 调用 NodeStatusStore 生成 cluster_id
        3. API 返回 new_cluster_id
        4. Node 记录返回的 cluster_id
        """
        loaded_models = self._get_loaded_models()
        
        report = {
            "type": "node_capacity_report",
            "node_id": self.node_id,
            "timestamp": timestamp,
            "capacity": {
                "workers_total": self._get_workers_total(),
                "workers_active": self._get_workers_active(),
                "max_concurrency_total": self._get_max_concurrency_total(),
            },
            "runtime": {
                "type": self.config.ollama_model.split(":")[0] if ":" in self.config.ollama_model else "ollama",
                "loaded_models": loaded_models,
            },
            "performance": {
                "max_token_throughput": self._estimate_token_throughput(),
            },
        }
        
        if self.config.use_websocket:
            self._send_ws_message(report)
        else:
            try:
                resp = requests.post(
                    f"{self.config.router_url}/api/v1/nodes/{self.node_id}/capacity_report",
                    json=report,
                    timeout=5,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    new_cluster_id = data.get("new_cluster_id")
                    if new_cluster_id:
                        self.set_cluster_id(new_cluster_id)
            except Exception as e:
                logger.warning(f"Failed to send capacity_report: {e}")
        
        # 更新本地 loaded_models
        self._check_and_update_cluster()
    
    # ===== GPU 监控 =====
    
    def _init_gpu_monitor(self):
        """初始化 GPU 监控器"""
        from ..utils.gpu_monitor import GPUMonitor
        self._gpu_monitor = GPUMonitor()
    
    def _get_vram_usage(self) -> float:
        """获取 VRAM 使用量 (GB)
        
        使用 GPU 监控模块获取真实数据
        """
        if hasattr(self, '_gpu_monitor'):
            info = self._gpu_monitor.get_gpu_info(0)
            if info:
                return info.vram_used_gb
        return 0.0
    
    def _get_vram_total(self) -> float:
        """获取 VRAM 总容量 (GB)
        
        使用 GPU 监控模块获取真实数据
        """
        if hasattr(self, '_gpu_monitor'):
            info = self._gpu_monitor.get_gpu_info(0)
            if info:
                return info.vram_total_gb
        return 0.0
    
    def _calculate_available_concurrency(self) -> int:
        """计算可用并发数
        
        基于 GPU VRAM 和 Worker 配置计算
        """
        # 估算单个 Job 需要的 VRAM
        # 假设每个模型占用约 8GB VRAM
        vram_per_job_gb = 8.0
        
        # 获取可用 VRAM
        available_vram_gb = self._get_vram_total() - self._get_vram_usage()
        
        # 基于 VRAM 计算最大并发
        vram_based_concurrency = int(available_vram_gb / vram_per_job_gb)
        
        # 取配置的并发和 VRAM 计算的并发的较小值
        return min(self.config.max_concurrent_jobs, max(1, vram_based_concurrency))
    
    def _calculate_available_token_capacity(self) -> int:
        """计算可用 token 容量
        
        基于可用 VRAM 和模型估算
        """
        # 获取 GPU 信息
        vram_total = self._get_vram_total()
        vram_used = self._get_vram_usage()
        vram_available = vram_total - vram_used
        
        if vram_available <= 0:
            return 0
        
        # 估算: 每 GB VRAM ≈ 1500 tokens 上下文容量
        # 这是一个简化估算，实际取决于模型大小
        tokens_per_gb = 1500
        
        # 考虑当前活跃 Job
        active_jobs = len([j for j in [self.current_job] if j])
        reserved_tokens = active_jobs * 500  # 每个活跃 Job 预留 500 tokens
        
        available_tokens = int(vram_available * tokens_per_gb) - reserved_tokens
        
        return max(0, available_tokens)
    
    def _get_workers_total(self) -> int:
        """获取 Worker 总数
        
        基于 GPU 数量和并发配置
        """
        if hasattr(self, '_gpu_monitor'):
            gpu_count = self._gpu_monitor.get_gpu_count()
            if gpu_count > 0:
                return gpu_count
        return 1
    
    def _get_workers_active(self) -> int:
        """获取活跃 Worker 数"""
        return 1 if self.current_job else 0
    
    def _get_max_concurrency_total(self) -> int:
        """获取总最大并发数
        
        基于 GPU VRAM 计算
        """
        vram_total = self._get_vram_total()
        if vram_total <= 0:
            return self.config.max_concurrent_jobs
        
        # 估算: 每个 Job 约 8GB VRAM
        vram_per_job = 8.0
        return min(self.config.max_concurrent_jobs, int(vram_total / vram_per_job))
    
    def _get_loaded_models(self) -> List[str]:
        """获取已加载模型列表"""
        # 尝试从 Ollama 获取实际加载的模型
        try:
            response = requests.get(f"{self.config.ollama_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                if models:
                    return models
        except Exception:
            pass
        
        # 回退到配置中的模型
        return [self.config.ollama_model]
    
    def _estimate_token_throughput(self) -> int:
        """估算 token 吞吐量 (tokens/秒)
        
        基于 GPU 性能估算
        """
        # 获取 GPU 利用率
        if hasattr(self, '_gpu_monitor'):
            utilization = self._gpu_monitor.get_average_utilization()
            
            # 估算基准吞吐量 (RTX 4090 约 100 tokens/s)
            base_throughput = 100
            
            # 根据利用率调整
            if utilization < 50:
                return int(base_throughput * 0.5)
            elif utilization < 80:
                return int(base_throughput * 0.8)
            else:
                return base_throughput
        
        return 50  # 默认估算
    
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
        """
        执行 Job (DCM v3.2 使用 Runtime Protocol)
        
        两种模式:
        1. 旧模式: 使用 self.ollama (兼容)
        2. 新模式: 使用 self.runtime (Runtime Protocol)
        """
        from ..models.runtime_protocol import (
            RuntimeRequest, RuntimeResponse, Message,
            GenerationParams, RuntimeLimits, RuntimeStatus
        )
        
        start_time = time.time()
        
        try:
            # 1. 构建 RuntimeRequest
            execution_id = f"exe_{job.job_id}"
            
            # 构建 messages
            if job.input_text:
                # 使用提供的 input_text
                messages = [Message(role="user", content=job.input_text)]
            else:
                # 简化: 使用 token 数构造提示
                messages = [Message(role="user", content=f"Process {job.input_tokens} input tokens")]
            
            # 构建 generation params
            generation = GenerationParams(
                temperature=0.7,
                max_tokens=job.output_tokens_limit,
                stream=False,
            )
            
            # 构建 limits
            limits = RuntimeLimits(
                input_tokens=job.input_tokens,
                output_tokens_limit=job.output_tokens_limit,
                max_latency_ms=job.max_latency,
            )
            
            # 创建请求
            request = RuntimeRequest(
                execution_id=execution_id,
                job_id=job.job_id,
                model=job.model or self.config.ollama_model,
                messages=messages,
                generation=generation,
                limits=limits,
                metadata={"node_id": self.node_id},
            )
            
            # 2. 使用 Runtime Protocol 执行
            response = self.runtime.execute(request)
            
            # 3. 处理结果
            if response.success:
                output_text = response.output
                actual_latency_ms = response.latency_ms
                actual_output_tokens = response.usage.output_tokens
            else:
                raise Exception(response.error or "Runtime execution failed")
            
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
