"""
Compatibility Matrix - DCM v3.0
模型兼容性匹配

匹配规则:
- Exact Match      = 1.0 (完全匹配)
- Family Match     = 0.8 (同家族 + 版本/Size 满足)
- Compatible Model = 0.6 (兼容模型)
- Cross Family     = 0.3 (跨家族兼容)
- Invalid          = 0.0 (无效)
"""

from typing import Dict, Set, Optional
from enum import Enum
import re


class CompatibilityLevel(str, Enum):
    """模型兼容等级"""
    EXACT = "exact"              # 精确匹配
    FAMILY = "family"            # 家族匹配（版本/Size 满足）
    COMPATIBLE = "compatible"     # 兼容模型
    CROSS_FAMILY = "cross_family" # 跨家族
    INVALID = "invalid"           # 无效


# 兼容性评分
COMPATIBILITY_SCORES: Dict[CompatibilityLevel, float] = {
    CompatibilityLevel.EXACT: 1.0,
    CompatibilityLevel.FAMILY: 0.8,
    CompatibilityLevel.COMPATIBLE: 0.6,
    CompatibilityLevel.CROSS_FAMILY: 0.3,
    CompatibilityLevel.INVALID: 0.0,
}


class ModelVersion:
    """模型版本解析"""
    
    def __init__(self, family: str, major: int, minor: int, suffix: str = ""):
        self.family = family.lower()
        self.major = major
        self.minor = minor
        self.suffix = suffix.lower()
    
    @property
    def full_version(self) -> float:
        return float(f"{self.major}.{self.minor}")
    
    def can_serve(self, required: "ModelVersion") -> bool:
        """检查是否可服务 required 模型
        
        规则:
        1. 同一家族
        2. 主版本 >= 要求（支持降级）
        3. Size >= 要求（只能大服务小）
        """
        if self.family != required.family:
            return False
        
        # 版本检查
        if self.full_version < required.full_version:
            return False
        
        # Size 检查
        if self.get_size_rank() < required.get_size_rank():
            return False
        
        return True
    
    def get_size_rank(self) -> int:
        """Size 排名（从小到大）"""
        size_map = {
            "1b": 1, "1.5b": 2, "2b": 3, "2.5b": 4, "3b": 5,
            "3.5b": 6, "4b": 7, "7b": 8, "8b": 9, "9b": 10,
            "12b": 11, "14b": 12, "32b": 13, "34b": 14, "70b": 15, "72b": 16,
            "e2b": 2, "e4b": 4, "e9b": 10, "e12b": 12, "e27b": 14,
            "latest": 20,
        }
        return size_map.get(self.suffix, 5)  # 默认值 5
    
    def __str__(self) -> str:
        return f"{self.family}{self.major}.{self.minor}:{self.suffix}"


def parse_model_name(name: str) -> ModelVersion:
    """解析模型名称
    
    支持格式:
    - qwen2.5:7b -> family=qwen, major=2, minor=5, suffix=7b
    - qwen2.5-7b -> family=qwen, major=2, minor=5, suffix=7b
    - qwen3.5:latest -> family=qwen, major=3, minor=5, suffix=latest
    """
    name = name.lower().replace("-", ":")
    
    parts = name.split(":")
    version_part = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""
    
    match = re.match(r'^([a-z]+)(\d+)\.?(\d*)$', version_part)
    if match:
        family = match.group(1)
        major = int(match.group(2))
        minor = int(match.group(3)) if match.group(3) else 0
    else:
        match = re.match(r'^([a-z]+)', version_part)
        family = match.group(1) if match else version_part
        major, minor = 1, 0
    
    return ModelVersion(family=family, major=major, minor=minor, suffix=suffix)


class CompatibilityMatrix:
    """
    模型兼容性矩阵 - DCM v3.0
    
    匹配规则:
    1. EXACT = 1.0 (完全匹配)
    2. FAMILY = 0.8 (同家族 + 版本/Size 满足)
    3. COMPATIBLE = 0.6 (兼容模型)
    4. CROSS_FAMILY = 0.3 (跨家族兼容)
    5. INVALID = 0.0 (无效)
    
    版本覆盖规则:
    - 4.0 → 3.5 → 3.0 → 2.5 → 2.0 (可降级)
    - 14b → 7b → 2b (只能大服务小)
    """
    
    def __init__(self):
        # 兼容模型映射
        self._compatible: Dict[str, Set[str]] = {
            "qwen2.5:7b": {"qwen2.5:14b", "qwen2.5:32b", "qwen3.5:latest", "qwen3:latest"},
            "qwen3.5:latest": {"qwen2.5:7b", "qwen2.5:14b", "qwen3:latest"},
            "qwen3:latest": {"qwen2.5:7b", "qwen2.5:14b", "qwen2.5:32b"},
            "gemma4:e4b": {"gemma4:e9b", "gemma3:e4b", "gemma3:e12b"},
            "gemma4:e9b": {"gemma3:e4b", "gemma3:e12b"},
            "llama3-8b": {"llama3.1-8b", "llama3.2-8b"},
            "llama3.1-8b": {"llama3.2-8b"},
        }
    
    def get_compatibility(self, job_model: Optional[str], slot_model: str) -> float:
        """获取兼容性评分"""
        level = self.get_compatibility_level(job_model, slot_model)
        return COMPATIBILITY_SCORES.get(level, 0.0)
    
    def get_compatibility_level(self, job_model: Optional[str], slot_model: str) -> CompatibilityLevel:
        """获取兼容性等级"""
        # 通用任务（无 model 要求）
        if not job_model:
            return CompatibilityLevel.FAMILY
        
        # 标准化
        job_normalized = job_model.lower().replace("-", ":")
        slot_normalized = slot_model.lower().replace("-", ":")
        
        # EXACT Match
        if job_normalized == slot_normalized:
            return CompatibilityLevel.EXACT
        
        job_version = parse_model_name(job_model)
        slot_version = parse_model_name(slot_model)
        
        # 同一家族
        if job_version.family == slot_version.family:
            # 检查版本/Size 是否满足
            if slot_version.can_serve(job_version):
                return CompatibilityLevel.FAMILY
            else:
                return CompatibilityLevel.INVALID
        
        # 跨家族检查兼容模型
        if self._is_compatible(job_normalized, slot_normalized):
            return CompatibilityLevel.COMPATIBLE
        
        # 跨家族
        return CompatibilityLevel.CROSS_FAMILY
    
    def _is_compatible(self, model1: str, model2: str) -> bool:
        """检查是否兼容"""
        compat1 = self._compatible.get(model1, set())
        if model2 in compat1:
            return True
        
        compat2 = self._compatible.get(model2, set())
        if model1 in compat2:
            return True
        
        return False
    
    def get_match_reason(self, job_model: str, slot_model: str) -> str:
        """获取匹配原因"""
        level = self.get_compatibility_level(job_model, slot_model)
        
        reasons = {
            CompatibilityLevel.EXACT: f"精确匹配 {job_model} == {slot_model}",
            CompatibilityLevel.FAMILY: f"家族匹配 {slot_model} 可服务 {job_model}",
            CompatibilityLevel.COMPATIBLE: f"兼容模型 {slot_model} 兼容 {job_model}",
            CompatibilityLevel.CROSS_FAMILY: f"跨家族 {slot_model} 与 {job_model}",
            CompatibilityLevel.INVALID: f"无效匹配 {slot_model} 无法服务 {job_model}",
        }
        
        return reasons.get(level, "未知")


# 全局实例
compatibility_matrix = CompatibilityMatrix()


# 测试
if __name__ == "__main__":
    matrix = CompatibilityMatrix()
    
    test_cases = [
        # (job, slot, expected_level, expected_score)
        ("qwen2.5:7b", "qwen2.5:7b", CompatibilityLevel.EXACT, 1.0),
        ("qwen2.5:7b", "qwen3.5:latest", CompatibilityLevel.FAMILY, 0.8),  # 版本更高
        ("qwen2.5:7b", "qwen2.5:14b", CompatibilityLevel.FAMILY, 0.8),    # Size 更大
        ("qwen2.5:7b", "qwen2.5:2b", CompatibilityLevel.INVALID, 0.0),    # Size 不足
        ("qwen3.5:latest", "qwen2.5:7b", CompatibilityLevel.INVALID, 0.0),  # 版本不足
        (None, "qwen2.5:7b", CompatibilityLevel.FAMILY, 0.8),  # 通用任务
    ]
    
    print("=== DCM v3.0 Compatibility Test ===")
    for job, slot, expected_level, expected_score in test_cases:
        actual_level = matrix.get_compatibility_level(job, slot)
        actual_score = matrix.get_compatibility(job, slot)
        
        status = "✓" if actual_level == expected_level and abs(actual_score - expected_score) < 0.01 else "✗"
        print(f"{status} {str(job or 'generic'):15} -> {slot:15} | {actual_level.value:12} ({actual_score:.2f})")
