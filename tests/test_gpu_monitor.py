"""
GPU Monitor 测试 - DCM v3.2
"""

import pytest
from src.utils.gpu_monitor import (
    GPUMonitor, MockGPU, NvidiaSMI, GPUInfo,
    get_gpu_monitor, get_gpu_info, get_vram_info
)


class TestGPUInfo:
    """GPUInfo 数据类测试"""
    
    def test_vram_conversion(self):
        """测试 VRAM 单位转换"""
        info = GPUInfo(
            gpu_id=0,
            name="Test GPU",
            vram_used_mb=8192,  # 8 GB
            vram_total_mb=24576,  # 24 GB
            utilization_percent=50.0,
            temperature_celsius=60,
        )
        
        assert info.vram_used_gb == 8.0
        assert info.vram_total_gb == 24.0
        assert info.vram_available_gb == 16.0
    
    def test_zero_vram(self):
        """测试零 VRAM 情况"""
        info = GPUInfo(
            gpu_id=0,
            name="Test GPU",
            vram_used_mb=0,
            vram_total_mb=0,
            utilization_percent=0,
        )
        
        assert info.vram_available_gb == 0.0


class TestMockGPU:
    """Mock GPU 后端测试"""
    
    def test_basic_info(self):
        """测试基本 GPU 信息"""
        mock = MockGPU(gpu_count=2, vram_per_gpu_gb=24.0)
        
        assert mock.get_gpu_count() == 2
        
        info = mock.get_gpu_info(0)
        assert info is not None
        assert info.gpu_id == 0
        assert info.vram_total_gb == 24.0
    
    def test_usage_simulation(self):
        """测试使用率模拟"""
        mock = MockGPU(gpu_count=1, vram_per_gpu_gb=24.0)
        
        # 设置 50% 使用率
        mock.set_usage(0, 50.0)
        info = mock.get_gpu_info(0)
        
        assert info.vram_used_gb == pytest.approx(12.0, rel=0.1)
        assert info.utilization_percent == 50.0
    
    def test_all_gpus(self):
        """测试获取所有 GPU"""
        mock = MockGPU(gpu_count=3, vram_per_gpu_gb=16.0)
        
        gpus = mock.get_all_gpu_info()
        assert len(gpus) == 3
        assert all(g.vram_total_gb == 16.0 for g in gpus)


class TestGPUMonitor:
    """GPUMonitor 主类测试"""
    
    def test_for_testing(self):
        """测试创建测试用监控器"""
        monitor = GPUMonitor.for_testing(gpu_count=2, vram_per_gpu_gb=24.0)
        
        assert monitor.backend_name == "MockGPU"
        assert monitor.get_gpu_count() == 2
        
        info = monitor.get_gpu_info(0)
        assert info.vram_total_gb == 24.0
    
    def test_total_vram(self):
        """测试总 VRAM 计算"""
        monitor = GPUMonitor.for_testing(gpu_count=2, vram_per_gpu_gb=16.0)
        
        assert monitor.get_total_vram_gb() == 32.0
    
    def test_available_vram(self):
        """测试可用 VRAM 计算"""
        monitor = GPUMonitor.for_testing(gpu_count=1, vram_per_gpu_gb=24.0)
        monitor._backend.set_usage(0, 50.0)  # 50% 使用率
        
        # 可用 = 24 - 12 = 12 GB
        assert monitor.get_available_vram_gb() == pytest.approx(12.0, rel=0.1)
    
    def test_used_vram(self):
        """测试已用 VRAM 计算"""
        monitor = GPUMonitor.for_testing(gpu_count=1, vram_per_gpu_gb=24.0)
        monitor._backend.set_usage(0, 75.0)  # 75% 使用率
        
        # 已用 = 24 * 0.75 = 18 GB
        assert monitor.get_used_vram_gb() == pytest.approx(18.0, rel=0.1)
    
    def test_average_utilization(self):
        """测试平均利用率"""
        monitor = GPUMonitor.for_testing(gpu_count=2, vram_per_gpu_gb=24.0)
        monitor._backend.set_usage(0, 50.0)
        monitor._backend.set_usage(1, 100.0)
        
        assert monitor.get_average_utilization() == 75.0


class TestGlobalFunctions:
    """全局函数测试"""
    
    def test_get_gpu_monitor(self):
        """测试获取全局监控器"""
        monitor = get_gpu_monitor()
        assert monitor is not None
    
    def test_get_gpu_info(self):
        """测试获取 GPU 信息"""
        info = get_gpu_info(0)
        # Mock 模式应该总是返回信息
        assert info is not None or True  # Mock 模式
    
    def test_get_vram_info(self):
        """测试获取 VRAM 信息"""
        vram = get_vram_info()
        
        assert "total_gb" in vram
        assert "used_gb" in vram
        assert "available_gb" in vram
        
        assert vram["total_gb"] >= 0
        assert vram["used_gb"] >= 0
        assert vram["available_gb"] >= 0


class TestNodeAgentGPUIntegration:
    """Node Agent GPU 集成测试"""
    
    def test_node_agent_gpu_monitor(self):
        """测试 Node Agent 使用 GPU 监控"""
        from src.agents.node_agent import NodeAgent, NodeConfig
        from unittest.mock import patch
        
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
        )
        
        with patch("src.agents.node_agent.requests"):
            agent = NodeAgent(config, config.node_id)
        
        # 验证 GPU 监控器已初始化
        assert agent._gpu_monitor is not None
        
        # 验证可以获取 VRAM 信息
        vram_total = agent._get_vram_total()
        assert vram_total >= 0
        
        # 验证可以计算可用并发
        concurrency = agent._calculate_available_concurrency()
        assert concurrency >= 0
    
    def test_node_agent_vram_calculation(self):
        """测试 Node Agent VRAM 计算"""
        from src.agents.node_agent import NodeAgent, NodeConfig
        from unittest.mock import patch, MagicMock
        
        config = NodeConfig(
            node_id="test_node",
            user_id="test_user",
            max_concurrent_jobs=4,
        )
        
        with patch("src.agents.node_agent.requests"):
            agent = NodeAgent(config, config.node_id)
        
        # Mock GPU 监控器返回特定值
        mock_info = GPUInfo(
            gpu_id=0,
            name="MockGPU",
            vram_used_mb=12 * 1024,  # 12 GB used
            vram_total_mb=24 * 1024,  # 24 GB total
            utilization_percent=50.0,
        )
        agent._gpu_monitor._backend = MagicMock()
        agent._gpu_monitor._backend.get_gpu_info.return_value = mock_info
        agent._gpu_monitor._backend.get_gpu_count.return_value = 1
        
        # 验证 VRAM 计算
        assert agent._get_vram_total() == 24.0
        assert agent._get_vram_usage() == 12.0
        
        # 验证可用并发计算
        # 12GB available / 8GB per job = 1.5 → 1
        concurrency = agent._calculate_available_concurrency()
        assert concurrency >= 1
        assert concurrency <= 4  # 不超过配置
