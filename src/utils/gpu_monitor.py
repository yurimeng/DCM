"""
GPU Monitor - GPU 监控模块
DCM v3.2

支持:
- NVIDIA GPU (nvidia-smi)
- AMD GPU (rocm-smi)
- 模拟模式 (开发/测试)
"""

import os
import subprocess
import re
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


@dataclass
class GPUInfo:
    """GPU 信息"""
    gpu_id: int
    name: str
    vram_used_mb: float
    vram_total_mb: float
    utilization_percent: float
    temperature_celsius: Optional[int] = None
    
    @property
    def vram_used_gb(self) -> float:
        return self.vram_used_mb / 1024
    
    @property
    def vram_total_gb(self) -> float:
        return self.vram_total_mb / 1024
    
    @property
    def vram_available_gb(self) -> float:
        return (self.vram_total_mb - self.vram_used_mb) / 1024


class GPUMonitorBackend(ABC):
    """GPU 监控后端接口"""
    
    @abstractmethod
    def get_gpu_count(self) -> int:
        """获取 GPU 数量"""
        pass
    
    @abstractmethod
    def get_gpu_info(self, gpu_id: int = 0) -> Optional[GPUInfo]:
        """获取单个 GPU 信息"""
        pass
    
    @abstractmethod
    def get_all_gpu_info(self) -> List[GPUInfo]:
        """获取所有 GPU 信息"""
        pass


class NvidiaSMI(GPUMonitorBackend):
    """NVIDIA GPU 监控 (nvidia-smi)"""
    
    def get_gpu_count(self) -> int:
        try:
            result = subprocess.run(
                ["nvidia-smi", "-L"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                lines = [l for l in result.stdout.strip().split('\n') if l]
                return len(lines)
        except Exception as e:
            logger.debug(f"nvidia-smi failed: {e}")
        return 0
    
    def get_gpu_info(self, gpu_id: int = 0) -> Optional[GPUInfo]:
        try:
            # 获取单个 GPU 信息
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits",
                    f"-i={gpu_id}"
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            if result.returncode != 0:
                return None
            
            line = result.stdout.strip()
            parts = [p.strip() for p in line.split(',')]
            
            if len(parts) >= 5:
                return GPUInfo(
                    gpu_id=int(parts[0]),
                    name=parts[1],
                    vram_used_mb=float(parts[2]),
                    vram_total_mb=float(parts[3]),
                    utilization_percent=float(parts[4]),
                    temperature_celsius=int(parts[5]) if len(parts) > 5 and parts[5] else None,
                )
        except Exception as e:
            logger.debug(f"nvidia-smi query failed: {e}")
        return None
    
    def get_all_gpu_info(self) -> List[GPUInfo]:
        results = []
        count = self.get_gpu_count()
        
        for i in range(count):
            info = self.get_gpu_info(i)
            if info:
                results.append(info)
        
        return results


class ROCmSMI(GPUMonitorBackend):
    """AMD GPU 监控 (rocm-smi)"""
    
    def get_gpu_count(self) -> int:
        try:
            result = subprocess.run(
                ["rocm-smi", "--showid"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                lines = [l for l in result.stdout.strip().split('\n') if 'gpu' in l.lower()]
                return len(lines)
        except Exception as e:
            logger.debug(f"rocm-smi failed: {e}")
        return 0
    
    def get_gpu_info(self, gpu_id: int = 0) -> Optional[GPUInfo]:
        try:
            # 获取单个 GPU 信息
            result = subprocess.run(
                [
                    "rocm-smi",
                    f"-i={gpu_id}",
                    "--showmeminfo=vram",
                    "--showutilization",
                    "--showtemp",
                    "--csv",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            if result.returncode != 0:
                return None
            
            lines = result.stdout.strip().split('\n')
            # 解析 CSV 输出
            # TODO: 实现 ROCm SMI 输出解析
            logger.debug(f"ROCm SMI output: {lines}")
            
        except Exception as e:
            logger.debug(f"rocm-smi query failed: {e}")
        return None
    
    def get_all_gpu_info(self) -> List[GPUInfo]:
        results = []
        count = self.get_gpu_count()
        
        for i in range(count):
            info = self.get_gpu_info(i)
            if info:
                results.append(info)
        
        return results


class MockGPU(GPUMonitorBackend):
    """模拟 GPU (开发/测试)"""
    
    def __init__(self, gpu_count: int = 1, vram_per_gpu_gb: float = 24.0):
        self._gpu_count = gpu_count
        self._vram_per_gpu_gb = vram_per_gpu_gb
        self._usage: Dict[int, float] = {}  # gpu_id -> usage_percent
    
    def set_usage(self, gpu_id: int, usage_percent: float) -> None:
        """设置 GPU 使用率 (0-100)"""
        self._usage[gpu_id] = usage_percent
    
    def get_gpu_count(self) -> int:
        return self._gpu_count
    
    def get_gpu_info(self, gpu_id: int = 0) -> Optional[GPUInfo]:
        if gpu_id >= self._gpu_count:
            return None
        
        usage = self._usage.get(gpu_id, 0.0)
        vram_used = (usage / 100.0) * self._vram_per_gpu_gb * 1024  # MB
        
        return GPUInfo(
            gpu_id=gpu_id,
            name=f"MockGPU-{gpu_id}",
            vram_used_mb=vram_used,
            vram_total_mb=self._vram_per_gpu_gb * 1024,
            utilization_percent=usage,
            temperature_celsius=50,
        )
    
    def get_all_gpu_info(self) -> List[GPUInfo]:
        return [self.get_gpu_info(i) for i in range(self._gpu_count)]


class GPUMonitor:
    """
    GPU 监控器
    
    自动检测并使用合适的 GPU 监控后端
    
    使用方式:
    ```python
    monitor = GPUMonitor()
    
    # 获取 GPU 数量
    count = monitor.get_gpu_count()
    
    # 获取单个 GPU 信息
    info = monitor.get_gpu_info(0)
    print(f"VRAM: {info.vram_used_gb:.1f}GB / {info.vram_total_gb:.1f}GB")
    
    # 获取所有 GPU 信息
    for gpu in monitor.get_all_gpu_info():
        print(f"GPU {gpu.gpu_id}: {gpu.name}")
    ```
    """
    
    def __init__(self, force_backend: Optional[str] = None):
        """
        Args:
            force_backend: 强制使用特定后端 ("nvidia", "rocm", "mock")
        """
        self._backend: Optional[GPUMonitorBackend] = None
        self._force_backend = force_backend
        self._detect_backend()
    
    def _detect_backend(self) -> None:
        """检测可用的 GPU 监控后端"""
        if self._force_backend:
            backend_name = self._force_backend.lower()
        else:
            # 自动检测
            backend_name = self._auto_detect()
        
        if backend_name == "nvidia":
            self._backend = NvidiaSMI()
            logger.info("Using NVIDIA GPU backend")
        elif backend_name == "rocm":
            self._backend = ROCmSMI()
            logger.info("Using AMD ROCm GPU backend")
        else:
            # 默认使用 Mock
            self._backend = MockGPU(gpu_count=1, vram_per_gpu_gb=24.0)
            logger.info("Using Mock GPU backend (no real GPU detected)")
    
    def _auto_detect(self) -> str:
        """自动检测 GPU 类型"""
        # 检查 NVIDIA
        try:
            result = subprocess.run(
                ["nvidia-smi", "--version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return "nvidia"
        except:
            pass
        
        # 检查 AMD ROCm
        try:
            result = subprocess.run(
                ["rocm-smi", "--version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return "rocm"
        except:
            pass
        
        return "mock"
    
    @property
    def backend_name(self) -> str:
        """获取后端名称"""
        return type(self._backend).__name__ if self._backend else "None"
    
    def get_gpu_count(self) -> int:
        """获取 GPU 数量"""
        if self._backend:
            return self._backend.get_gpu_count()
        return 0
    
    def get_gpu_info(self, gpu_id: int = 0) -> Optional[GPUInfo]:
        """获取单个 GPU 信息"""
        if self._backend:
            return self._backend.get_gpu_info(gpu_id)
        return None
    
    def get_all_gpu_info(self) -> List[GPUInfo]:
        """获取所有 GPU 信息"""
        if self._backend:
            return self._backend.get_all_gpu_info()
        return []
    
    def get_total_vram_gb(self) -> float:
        """获取总 VRAM (GB)"""
        total = 0.0
        for gpu in self.get_all_gpu_info():
            total += gpu.vram_total_gb
        return total
    
    def get_available_vram_gb(self) -> float:
        """获取可用 VRAM (GB)"""
        available = 0.0
        for gpu in self.get_all_gpu_info():
            available += gpu.vram_available_gb
        return available
    
    def get_used_vram_gb(self) -> float:
        """获取已用 VRAM (GB)"""
        used = 0.0
        for gpu in self.get_all_gpu_info():
            used += gpu.vram_used_gb
        return used
    
    def get_average_utilization(self) -> float:
        """获取平均利用率 (%)"""
        gpus = self.get_all_gpu_info()
        if not gpus:
            return 0.0
        return sum(g.utilization_percent for g in gpus) / len(gpus)
    
    @classmethod
    def for_testing(cls, gpu_count: int = 1, vram_per_gpu_gb: float = 24.0) -> "GPUMonitor":
        """创建用于测试的 Mock 监控器"""
        monitor = cls(force_backend="mock")
        monitor._backend = MockGPU(gpu_count=gpu_count, vram_per_gpu_gb=vram_per_gpu_gb)
        return monitor


# ===== 全局实例 =====
_gpu_monitor: Optional[GPUMonitor] = None


def get_gpu_monitor() -> GPUMonitor:
    """获取全局 GPU 监控器"""
    global _gpu_monitor
    if _gpu_monitor is None:
        _gpu_monitor = GPUMonitor()
    return _gpu_monitor


def get_gpu_info(gpu_id: int = 0) -> Optional[GPUInfo]:
    """便捷函数: 获取 GPU 信息"""
    return get_gpu_monitor().get_gpu_info(gpu_id)


def get_gpu_count() -> int:
    """便捷函数: 获取 GPU 数量"""
    return get_gpu_monitor().get_gpu_count()


def get_vram_info() -> Dict[str, float]:
    """便捷函数: 获取 VRAM 信息"""
    monitor = get_gpu_monitor()
    return {
        "total_gb": monitor.get_total_vram_gb(),
        "used_gb": monitor.get_used_vram_gb(),
        "available_gb": monitor.get_available_vram_gb(),
    }
