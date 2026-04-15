"""
Node Models - DCM v3.2
Node = 计算能力(capability) + 实时状态(state) + 市场报价(pricing) 的算力原子单元
"""

from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict, Any
from enum import Enum


# ===== 嵌套结构 =====

class Location(BaseModel):
    """地理位置信息"""
    region: str = Field(default="unknown", description="区域")
    hostname: str = Field(default="", description="主机名")


class Hardware(BaseModel):
    """硬件信息 (自动生成)"""
    gpu_type: str = Field(default="unknown", description="GPU 型号")
    gpu_count: int = Field(default=1, ge=1, description="GPU 数量")
    vram_per_gpu_gb: float = Field(default=0.0, description="每卡显存 (GB)")


class Runtime(BaseModel):
    """运行时信息 (随状态更新)"""
    type: str = Field(default="", description="Runtime 类型: ollama, vllm, tensorrt")
    loaded_models: List[str] = Field(default_factory=list, description="已加载模型列表")


class Capability(BaseModel):
    """计算能力 (自动计算)"""
    max_concurrency_total: int = Field(default=1, ge=1, description="最大并发总数")
    tokens_per_sec: int = Field(default=0, description="Token 吞吐量 (tokens/sec)")
    max_queue_tokens: int = Field(default=1500, ge=1, description="最大队列 (tokens)")


class Pricing(BaseModel):
    """市场报价 (用户定义，随时可调整)"""
    ask_price_usdc_per_mtoken: float = Field(
        default=0.000001,  # USDC per token (1 USDC/1M tokens)
        gt=0, 
        alias="ask_price", 
        description="报价 USDC per token (0.000001 = 1 USDC/1M tokens)"
    )
    avg_latency_ms: int = Field(default=100, ge=0, description="平均延迟 (ms)")


class Reliability(BaseModel):
    """可靠性指标 (统计下发)"""
    avg_latency_ms: int = Field(default=0, ge=0, description="平均延迟 (ms)")
    success_rate: float = Field(default=0.95, ge=0, le=1, description="成功率")
    quality_score: float = Field(default=0.9, ge=0, le=1, description="质量评分")


class Economy(BaseModel):
    """经济模型"""
    stake_amount: float = Field(default=0.0, description="已质押金额")
    stake_required: float = Field(default=0.0, description="所需质押金额")
    stake_tier: str = Field(default="personal", description="质押等级: personal, professional, enterprise")


class NodeState(BaseModel):
    """实时状态 (随心跳更新)"""
    status: str = Field(default="offline", description="状态: offline, online, busy, locked")
    active_jobs: int = Field(default=0, ge=0, description="活跃 Job 数")
    available_concurrency: int = Field(default=1, ge=0, description="可用并发数")
    available_queue_tokens: int = Field(default=1500, ge=0, description="可用队列 tokens")


class Network(BaseModel):
    """网络/集群信息"""
    cluster_id: Optional[str] = Field(None, description="所属 Cluster ID")


# ===== Tier 枚举 =====

class NodeTier(str, Enum):
    """Node 等级分类"""
    PERSONAL = "personal"      # < 4 GPU
    PROFESSIONAL = "professional"  # 4-7 GPU
    ENTERPRISE = "enterprise"  # >= 8 GPU


class NodeStatus(str, Enum):
    """Node 状态"""
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    LOCKED = "locked"


# ===== 主模型 =====

class NodeCreate(BaseModel):
    """Node 创建请求"""
    # 基础信息
    user_id: str = Field(..., description="用户 ID (服务器所有者)")
    
    # 可选字段 (可以为空，后续心跳更新)
    location: Optional[Location] = None
    hardware: Optional[Hardware] = None
    runtime: Optional[Runtime] = None
    pricing: Optional[Pricing] = None
    
    @model_validator(mode='after')
    def init_defaults(self) -> 'NodeCreate':
        """初始化默认值"""
        if self.location is None:
            self.location = Location()
        if self.hardware is None:
            self.hardware = Hardware()
        if self.runtime is None:
            self.runtime = Runtime()
        if self.pricing is None:
            self.pricing = Pricing()
        return self


class Node(BaseModel):
    """
    Node 算力原子单元 - DCM v3.2
    
    Node 是一个同时具备:
    - 计算能力 (capability)
    - 实时状态 (state)
    - 市场报价 (pricing)
    
    的算力原子单元
    
    Cluster 分配:
    - Node 注册时自动分配 cluster_id
    - 依据: region -> stake_tier -> loaded_models -> reliability
    - 在 Node Capacity Report 时检查是否需要更新
    """
    # ===== 标识 =====
    node_id: str = Field(default="", description="Node ID (自动生成)")
    user_id: str = Field(default="", description="用户 ID (关联钱包，影响收入)")
    
    # ===== 嵌套结构 =====
    location: Location = Field(default_factory=Location, description="地理位置")
    hardware: Hardware = Field(default_factory=Hardware, description="硬件信息")
    runtime: Runtime = Field(default_factory=Runtime, description="运行时信息")
    capability: Capability = Field(default_factory=Capability, description="计算能力")
    pricing: Pricing = Field(default_factory=Pricing, description="市场报价")
    reliability: Reliability = Field(default_factory=Reliability, description="可靠性指标")
    economy: Economy = Field(default_factory=Economy, description="经济模型")
    state: NodeState = Field(default_factory=NodeState, description="实时状态")
    network: Network = Field(default_factory=Network, description="网络/集群信息")
    
    # ===== Cluster 分配方法 =====
    
    def assign_cluster(self) -> str:
        """
        根据 Node 属性分配 Cluster ID
        
        依据: region -> stake_tier -> loaded_models -> reliability
        格式: cluster_{region}_{stake_tier}_{model_family}_{reliability_tier}
        
        Returns:
            Cluster ID
        """
        from src.services.cluster_builder import build_cluster_id
        
        self.network.cluster_id = build_cluster_id(
            region=self.location.region,
            stake_tier=self.economy.stake_tier,
            models=self.runtime.loaded_models,
            reliability=self.reliability
        )
        return self.network.cluster_id
    
    def check_and_update_cluster(self) -> Optional[str]:
        """
        检查并更新 Cluster ID
        
        在 Node Capacity Report 时调用
        如果 region/stake_tier/models/reliability 变化则更新
        
        Returns:
            新的 cluster_id 或 None
        """
        from src.services.cluster_builder import update_node_cluster
        
        return update_node_cluster(self)
    
    # ===== 兼容字段 (扁平化接口) =====
    # 为了向后兼容，保留一些扁平字段的 getter/setter
    
    @property
    def status(self) -> str:
        """兼容属性"""
        return self.state.status
    
    @status.setter
    def status(self, v: str) -> None:
        self.state.status = v
    
    @property
    def gpu_type(self) -> str:
        return self.hardware.gpu_type
    
    @property
    def gpu_count(self) -> int:
        return self.hardware.gpu_count
    
    @property
    def avg_latency_ms(self) -> int:
        return self.reliability.avg_latency_ms
    
    @property
    def success_rate(self) -> float:
        return self.reliability.success_rate
    
    @property
    def ask_price(self) -> float:
        return self.pricing.ask_price_usdc_per_mtoken
    
    @property
    def model_support(self) -> List[str]:
        """兼容属性：返回 runtime.loaded_models"""
        return self.runtime.loaded_models
    
    @property
    def avg_latency(self) -> int:
        """兼容属性：返回 reliability.avg_latency_ms"""
        return self.reliability.avg_latency_ms
    
    @property
    def avg_success_rate(self) -> float:
        """兼容属性：返回 reliability.success_rate"""
        return self.reliability.success_rate
    
    @property
    def avg_quality_score(self) -> float:
        """兼容属性：返回 reliability.quality_score"""
        return self.reliability.quality_score
    
    @property
    def available_concurrency(self) -> int:
        return self.state.available_concurrency
    
    @property
    def available_queue_tokens(self) -> int:
        return self.state.available_queue_tokens
    
    # ===== 方法 =====
    
    def is_available(self) -> bool:
        """Node 是否可用"""
        return self.state.status in ["online", "busy"] and self.state.available_concurrency > 0
    
    def is_idle(self) -> bool:
        """Node 是否空闲"""
        return self.state.available_queue_tokens > 0
    
    def get_tier(self) -> NodeTier:
        """根据 GPU 数量获取等级"""
        if self.hardware.gpu_count >= 8:
            return NodeTier.ENTERPRISE
        elif self.hardware.gpu_count >= 4:
            return NodeTier.PROFESSIONAL
        return NodeTier.PERSONAL
    
    def get_stake_required(self) -> float:
        """获取所需质押"""
        tier = self.get_tier()
        if tier == NodeTier.ENTERPRISE:
            return 1000.0
        elif tier == NodeTier.PROFESSIONAL:
            return 200.0
        return 50.0
    
    def update_state(self, live_status: Dict) -> None:
        """从 Node Live Status Report 更新状态"""
        if "status" in live_status:
            self.state.status = live_status["status"].get("vram_used_gb", "online")
        if "capacity" in live_status:
            self.state.available_concurrency = live_status["capacity"].get("max_concurrency_available", 1)
        if "load" in live_status:
            self.state.active_jobs = live_status["load"].get("active_jobs", 0)
            self.state.available_queue_tokens = live_status["load"].get("available_token_capacity", 0)
    
    def update_capacity(self, capacity_report: Dict) -> None:
        """从 Node Capacity Report 更新能力"""
        if "capacity" in capacity_report:
            cap = capacity_report["capacity"]
            self.capability.max_concurrency_total = cap.get("max_concurrency_total", 1)
            self.state.available_concurrency = cap.get("max_concurrency_available", cap.get("max_concurrency_total", 1))
        
        if "runtime" in capacity_report:
            rt = capacity_report["runtime"]
            self.runtime.type = rt.get("type", "")
            self.runtime.loaded_models = rt.get("loaded_models", [])
        
        if "performance" in capacity_report:
            perf = capacity_report["performance"]
            self.capability.tokens_per_sec = perf.get("max_token_throughput", 0)


class NodeResponse(BaseModel):
    """Node API 响应"""
    node_id: str
    user_id: str
    status: str
    stake_required: float
    stake_amount: float
    gpu_type: str
    gpu_count: int
    slot_count: int = 0
    worker_count: int = 0
    next_step: Optional[str] = None
    cluster_id: Optional[str] = Field(None, description="分配的 Cluster ID")


class NodePollResponse(BaseModel):
    """Node 轮询响应"""
    has_job: bool
    job_id: Optional[str] = None
    # model 统一为 Dict 结构 (DCM v3.2)
    model: Optional[Dict[str, Any]] = Field(
        default=None,
        description="模型信息: {name, family, context_window, ...}"
    )
    timeout_seconds: Optional[int] = None
    pre_lock_expires_at: Optional[str] = None
    # 扩展字段
    model_info: Optional[Dict[str, Any]] = Field(
        default=None,
        description="扩展模型信息 (已废弃，统一使用 model)"
    )
    execution_id: Optional[str] = None
    slot_id: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    generation: Optional[Dict[str, Any]] = None
    runtime: Optional[Dict[str, Any]] = None
    locked_price: Optional[float] = None


class NodeResultSubmit(BaseModel):
    """Node 结果提交"""
    match_id: str
    result: str
    result_hash: Optional[str] = None
    actual_latency_ms: int
    actual_tokens: int
    error_message: Optional[str] = None
