"""
System Info Detection Module
系统信息检测模块

Detects:
- GPU/Chipset info: chipset, qty, vram, pooled
- OS info: name, version

检测：
- GPU/芯片组信息：chipset, qty, vram, pooled
- 操作系统信息：name, version
"""

import platform
import subprocess
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class OSPlatform(Enum):
    """OS Platform Types / 操作系统平台类型"""
    MACOS = "macos"
    LINUX = "linux"
    WINDOWS = "windows"
    UNKNOWN = "unknown"


@dataclass
class GPUInfo:
    """
    GPU Information / GPU 信息
    
    Attributes:
        chipset: GPU chip name (e.g., "Apple M5 Pro", "RTX 4090", "MI300X")
        qty: Number of GPUs (1 for integrated, N for discrete)
        vram_gb: VRAM per GPU in GB (0 for unified memory)
        pooled: Whether GPU can be pooled (multiple GPUs for single workload)
    """
    chipset: str
    qty: int = 1
    vram_gb: float = 0.0
    pooled: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary / 转换为字典"""
        return {
            "chipset": self.chipset,
            "qty": self.qty,
            "vram_gb": self.vram_gb,
            "pooled": self.pooled,
        }


@dataclass
class OSInfo:
    """
    Operating System Information / 操作系统信息
    
    Attributes:
        name: OS name (e.g., "macOS", "Ubuntu", "Windows")
        version: OS version (e.g., "15.4.0", "22.04", "11")
        platform: OS platform type
        kernel: Kernel version
    """
    name: str
    version: str
    platform: OSPlatform = OSPlatform.UNKNOWN
    kernel: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary / 转换为字典"""
        return {
            "name": self.name,
            "version": self.version,
            "platform": self.platform.value,
            "kernel": self.kernel,
        }


@dataclass
class SystemInfo:
    """
    Complete System Information / 完整系统信息
    
    Contains:
    - GPU/Chipset info (chipset, qty, vram, pooled)
    - OS info (name, version)
    - Additional metadata
    
    包含：
    - GPU/芯片组信息 (chipset, qty, vram, pooled)
    - 操作系统信息 (name, version)
    - 附加元数据
    """
    gpu: GPUInfo
    os: OSInfo
    hostname: str = ""
    total_memory_gb: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary / 转换为字典"""
        return {
            "gpu": self.gpu.to_dict(),
            "os": self.os.to_dict(),
            "hostname": self.hostname,
            "total_memory_gb": self.total_memory_gb,
            "metadata": self.metadata,
        }
    
    def to_registration_payload(self) -> Dict[str, Any]:
        """
        Convert to node registration payload
        转换为节点注册载荷
        """
        return {
            "chipset": self.gpu.chipset,
            "gpu_qty": self.gpu.qty,
            "gpu_vram_gb": self.gpu.vram_gb,
            "gpu_pooled": self.gpu.pooled,
            "os_name": self.os.name,
            "os_version": self.os.version,
            "hostname": self.hostname,
            # Legacy fields for backward compatibility
            "gpu_type": self.gpu.chipset,
            "vram_gb": self._estimate_vram_for_registration(),
        }
    
    def _estimate_vram_for_registration(self) -> float:
        """
        Estimate VRAM for legacy registration
        估算用于旧版注册的 VRAM
        
        For Apple Silicon: Use unified memory
        For NVIDIA/AMD: Use actual VRAM
        """
        if self.gpu.vram_gb > 0:
            return self.gpu.vram_gb
        # Apple Silicon uses unified memory, estimate based on total
        return self.total_memory_gb * 0.75  # Reserve 25% for system
    
    def __str__(self) -> str:
        """String representation / 字符串表示"""
        return f"SystemInfo(gpu={self.gpu.chipset} x{self.gpu.qty}, os={self.os.name} {self.os.version})"


class SystemInfoDetector:
    """
    System Information Detector
    系统信息检测器
    
    Detects GPU, OS, and other system information
    检测 GPU、操作系统和其他系统信息
    """
    
    @staticmethod
    def detect() -> SystemInfo:
        """
        Detect all system information
        检测所有系统信息
        """
        gpu = SystemInfoDetector.detect_gpu()
        os_info = SystemInfoDetector.detect_os()
        
        return SystemInfo(
            gpu=gpu,
            os=os_info,
            hostname=platform.node(),
            total_memory_gb=SystemInfoDetector._get_total_memory_gb(),
            metadata={
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python_version": platform.python_version(),
            }
        )
    
    @staticmethod
    def detect_gpu() -> GPUInfo:
        """
        Detect GPU information
        检测 GPU 信息
        
        Supports:
        - macOS: Apple Silicon, Intel Mac
        - Linux: NVIDIA, AMD, Intel GPUs
        - Windows: NVIDIA, AMD, Intel GPUs
        
        Returns:
            GPUInfo with chipset, qty, vram, pooled
        """
        system = platform.system()
        
        if system == "Darwin":
            return SystemInfoDetector._detect_macos_gpu()
        elif system == "Linux":
            return SystemInfoDetector._detect_linux_gpu()
        elif system == "Windows":
            return SystemInfoDetector._detect_windows_gpu()
        else:
            logger.warning(f"Unknown system: {system}, using generic GPU info")
            return GPUInfo(chipset="Unknown", qty=1, vram_gb=0, pooled=False)
    
    @staticmethod
    def _detect_macos_gpu() -> GPUInfo:
        """
        Detect GPU on macOS
        检测 macOS 上的 GPU
        """
        try:
            # Get chip type from hardware info
            result = subprocess.run(
                ["system_profiler", "SPHardwareDataType", "-json"],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode != 0:
                return GPUInfo(chipset="Apple Silicon", qty=1, vram_gb=0, pooled=False)
            
            data = json.loads(result.stdout)
            hw_data = data.get("SPHardwareDataType", [{}])[0]
            
            chip_type = hw_data.get("chip_type", "Apple Silicon")
            
            # Get memory info
            physical_memory = hw_data.get("physical_memory", "0 GB")
            total_memory_gb = SystemInfoDetector._parse_memory_gb(physical_memory)
            
            # Parse processor info to determine GPU cores
            proc_info = hw_data.get("number_processors", "proc 10:0:0:0")
            
            # Apple Silicon: GPU is integrated, not poolable
            # VRAM is unified memory (shared with CPU)
            return GPUInfo(
                chipset=chip_type,
                qty=1,  # Integrated GPU
                vram_gb=0,  # Unified memory
                pooled=False  # Cannot pool integrated GPU
            )
            
        except Exception as e:
            logger.warning(f"macOS GPU detection failed: {e}")
            return GPUInfo(chipset="Apple Silicon", qty=1, vram_gb=0, pooled=False)
    
    @staticmethod
    def _detect_linux_gpu() -> GPUInfo:
        """
        Detect GPU on Linux
        检测 Linux 上的 GPU
        
        Tries: nvidia-smi, rocm-smi, lspci
        """
        # Try NVIDIA first
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                gpus = []
                for line in lines:
                    parts = line.split(",")
                    if len(parts) >= 2:
                        name = parts[0].strip()
                        memory = parts[1].strip()
                        vram = SystemInfoDetector._parse_memory_gb(memory)
                        gpus.append((name, vram))
                
                if gpus:
                    # Check if poolable (multiple same GPUs)
                    qty = len(gpus)
                    pooled = qty > 1
                    
                    return GPUInfo(
                        chipset=gpus[0][0],  # Use first GPU name
                        qty=qty,
                        vram_gb=gpus[0][1],
                        pooled=pooled
                    )
        except FileNotFoundError:
            pass
        
        # Try AMD ROCm
        try:
            result = subprocess.run(
                ["rocm-smi", "--showproductname", "--json"],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                # Parse AMD GPU info
                # ... (simplified)
        except FileNotFoundError:
            pass
        
        # Fallback: try lspci
        try:
            result = subprocess.run(
                ["lspci"],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                output = result.stdout.lower()
                if "nvidia" in output:
                    return GPUInfo(chipset="NVIDIA GPU", qty=1, vram_gb=0, pooled=False)
                elif "amd" in output or "radeon" in output:
                    return GPUInfo(chipset="AMD GPU", qty=1, vram_gb=0, pooled=False)
        except FileNotFoundError:
            pass
        
        return GPUInfo(chipset="Unknown", qty=1, vram_gb=0, pooled=False)
    
    @staticmethod
    def _detect_windows_gpu() -> GPUInfo:
        """
        Detect GPU on Windows
        检测 Windows 上的 GPU
        """
        try:
            # Use wmic or powershell to get GPU info
            result = subprocess.run(
                ["powershell", "-Command", "Get-WmiObject Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json"],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if isinstance(data, list):
                    data = data[0]
                
                name = data.get("Name", "Unknown")
                vram = data.get("AdapterRAM", 0)
                vram_gb = vram / (1024**3) if vram > 0 else 0
                
                return GPUInfo(
                    chipset=name,
                    qty=1,
                    vram_gb=round(vram_gb, 1),
                    pooled=False
                )
        except Exception as e:
            logger.warning(f"Windows GPU detection failed: {e}")
        
        return GPUInfo(chipset="Unknown", qty=1, vram_gb=0, pooled=False)
    
    @staticmethod
    def detect_os() -> OSInfo:
        """
        Detect OS information
        检测操作系统信息
        """
        system = platform.system()
        name = ""
        platform_type = OSPlatform.UNKNOWN
        
        if system == "Darwin":
            name = "macOS"
            platform_type = OSPlatform.MACOS
        elif system == "Linux":
            name = SystemInfoDetector._detect_linux_distro()
            platform_type = OSPlatform.LINUX
        elif system == "Windows":
            name = "Windows"
            platform_type = OSPlatform.WINDOWS
        
        return OSInfo(
            name=name,
            version=platform.release(),
            platform=platform_type,
            kernel=platform.version()
        )
    
    @staticmethod
    def _detect_linux_distro() -> str:
        """
        Detect Linux distribution
        检测 Linux 发行版
        """
        # Try /etc/os-release
        try:
            with open("/etc/os-release", "r") as f:
                content = f.read()
                for line in content.split("\n"):
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=")[1].strip().strip('"')
        except FileNotFoundError:
            pass
        
        # Try lsb_release
        try:
            result = subprocess.run(
                ["lsb_release", "-ds"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except FileNotFoundError:
            pass
        
        return "Linux"
    
    @staticmethod
    def _parse_memory_gb(memory_str: str) -> float:
        """
        Parse memory string to GB
        将内存字符串解析为 GB
        """
        # Handle formats like "24 GB", "16384 MB", "16G"
        memory_str = memory_str.strip().upper()
        
        match = re.match(r"([\d.]+)\s*(GB|MB|TB|G|M|T)?", memory_str)
        if not match:
            return 0.0
        
        value = float(match.group(1))
        unit = match.group(2) or "GB"
        
        if unit in ("TB", "T"):
            return value * 1024
        elif unit in ("GB", "G"):
            return value
        elif unit in ("MB", "M"):
            return value / 1024
        else:
            return value
    
    @staticmethod
    def _get_total_memory_gb() -> float:
        """
        Get total system memory in GB
        获取系统总内存（GB）
        """
        system = platform.system()
        
        if system == "Darwin":
            try:
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    bytes_mem = int(result.stdout.strip())
                    return bytes_mem / (1024**3)
            except:
                pass
        elif system == "Linux":
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            return kb / (1024**2)
            except:
                pass
        elif system == "Windows":
            try:
                result = subprocess.run(
                    ["powershell", "-Command", "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    bytes_mem = int(result.stdout.strip())
                    return bytes_mem / (1024**3)
            except:
                pass
        
        return 0.0


# Singleton instance
_detector = SystemInfoDetector

def get_system_info() -> SystemInfo:
    """
    Get system information (convenience function)
    获取系统信息（便捷函数）
    """
    return _detector.detect()


def detect_gpu() -> GPUInfo:
    """
    Detect GPU information (convenience function)
    检测 GPU 信息（便捷函数）
    """
    return _detector.detect_gpu()


def detect_os() -> OSInfo:
    """
    Detect OS information (convenience function)
    检测操作系统信息（便捷函数）
    """
    return _detector.detect_os()
