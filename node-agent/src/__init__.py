"""
DCM Node Agent - macOS 一键安装版

基于 Runtime Adapter Layer (RAL) 架构

包含模块:
- system_info: 系统信息检测 (GPU, OS, 主机名)
- runtime_adapter: 运行时适配器
- network: 网络适配器
- node_agent: 节点代理核心
"""

from .system_info import (
    SystemInfo,
    GPUInfo,
    OSInfo,
    SystemInfoDetector,
    get_system_info,
    detect_gpu,
    detect_os,
    OSPlatform,
)

__version__ = "1.1.0"
