"""
F14: QUIC Transport - 数据模型

推理数据的可靠传输层模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class InferenceStatus(Enum):
    """推理状态"""
    PENDING = "pending"
    RUNNING = "running"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ConnectionState(Enum):
    """连接状态"""
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"


@dataclass
class InferenceRequest:
    """推理请求"""
    job_id: str
    match_id: str
    model: str
    prompt: str
    max_tokens: int = 256
    temperature: float = 0.7
    stream: bool = True
    timeout_ms: int = 30000
    
    # 追踪字段
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def start(self):
        self.started_at = datetime.utcnow()
    
    def complete(self):
        self.completed_at = datetime.utcnow()
    
    @property
    def latency_ms(self) -> int:
        if not self.started_at:
            return 0
        end = self.completed_at or datetime.utcnow()
        return int((end - self.started_at).total_seconds() * 1000)


@dataclass
class StreamingToken:
    """Streaming Token"""
    token: str
    index: int
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class InferenceResult:
    """推理结果"""
    job_id: str
    result_text: str = ""
    result_hash: str = ""  # SHA256 hash
    tokens_count: int = 0
    actual_latency_ms: int = 0
    streaming_complete: bool = False
    error: Optional[str] = None
    completed_at: datetime = field(default_factory=datetime.utcnow)
    
    # 错误信息
    error_code: Optional[str] = None
    retry_count: int = 0


@dataclass
class InferenceSession:
    """推理会话 (追踪一个推理任务)"""
    job_id: str
    match_id: str
    request: InferenceRequest
    status: InferenceStatus = InferenceStatus.PENDING
    
    # Streaming 缓冲
    tokens: List[StreamingToken] = field(default_factory=list)
    
    # 结果
    result: Optional[InferenceResult] = None
    
    # 连接信息
    quic_connection_id: Optional[str] = None
    stream_id: Optional[int] = None
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def add_token(self, token: str):
        """添加 token 到结果"""
        self.tokens.append(StreamingToken(
            token=token,
            index=len(self.tokens)
        ))
    
    @property
    def result_text(self) -> str:
        return "".join(t.token for t in self.tokens)
    
    @property
    def tokens_count(self) -> int:
        return len(self.tokens)
    
    @property
    def is_complete(self) -> bool:
        return self.status in (InferenceStatus.COMPLETED, InferenceStatus.FAILED, InferenceStatus.TIMEOUT)


@dataclass
class QUICConfig:
    """QUIC 配置"""
    # 连接配置
    server_host: str = "0.0.0.0"
    server_port: int = 8443
    
    # 行为配置
    connection_timeout_ms: int = 10000
    stream_timeout_ms: int = 60000
    max_concurrent_streams: int = 100
    
    # 性能配置
    enable_0_rtt: bool = True  # 0-RTT 恢复
    congestion_control: str = "cubic"  # cubic 或 bbr
    max_datagram_size: int = 1200
    
    # 重试配置
    max_retry_count: int = 3
    retry_delay_ms: int = 1000
    
    # 带宽限制 (bytes/s)
    max_bandwidth_per_connection: int = 10 * 1024 * 1024  # 10 Mbps


@dataclass
class QUICMetrics:
    """QUIC 指标"""
    active_sessions: int = 0
    total_sessions: int = 0
    completed_sessions: int = 0
    failed_sessions: int = 0
    
    # 延迟统计
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # 吞吐量
    tokens_processed: int = 0
    bytes_transferred: int = 0
    
    # 连接统计
    connections_established: int = 0
    connections_failed: int = 0
