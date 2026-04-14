"""
Compatibility Module - DCM v3.1
Model Compatibility Matching (Dynamic Configuration)
模型兼容性匹配（动态配置版）
"""

from typing import Dict, Set, Optional, List
from enum import Enum
import re
import os
import yaml


class CompatibilityLevel(str, Enum):
    """Model compatibility levels / 模型兼容等级"""
    EXACT = "exact"              # Exact match / 精确匹配
    FAMILY = "family"            # Family match / 家族匹配
    COMPATIBLE = "compatible"     # Compatible model / 兼容模型
    CROSS_FAMILY = "cross_family" # Cross-family / 跨家族兼容
    INVALID = "invalid"           # Invalid / 无效


class ModelConfig:
    """
    Model Configuration Manager (Dynamic Loading)
    模型配置管理器（动态加载）
    
    Loads from config/models.yaml
    从配置文件动态加载
    """
    
    _instance = None
    _config = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """
        Load configuration from YAML file
        从 YAML 文件加载配置
        """
        config_path = os.environ.get(
            "DCM_MODEL_CONFIG",
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "models.yaml")
        )
        
        # Try multiple paths
        paths_to_try = [
            config_path,
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "models.yaml"),
            "/Users/yurimeng/Code/Platform/DCM/config/models.yaml",
        ]
        
        for path in paths_to_try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    self._config = yaml.safe_load(f)
                return
        
        # Fallback to minimal default config
        self._config = self._get_default_config()
    
    def _get_default_config(self) -> Dict:
        """Get default configuration / 获取默认配置"""
        return {
            "model_families": {
                "qwen": {
                    "versions": ["2.5", "3.0", "3.5"],
                    "sizes": ["2b", "7b", "14b", "32b", "latest"],
                },
                "llama": {
                    "versions": ["2", "3", "3.1", "3.2"],
                    "sizes": ["8b", "70b"],
                },
                "gemma": {
                    "versions": ["3", "4"],
                    "sizes": ["e2b", "e4b", "e9b", "e12b", "e27b"],
                },
            },
            "compatibility": {
                "version_order": {
                    "ascending": ["2.0", "2.5", "3.0", "3.5", "4.0"]
                },
                "size_order": {
                    "ascending": ["2b", "7b", "8b", "14b", "32b", "70b"]
                },
                "scoring_weights": {
                    "exact_match": 1.0,
                    "family_match": 0.8,
                    "compatible": 0.6,
                    "cross_family": 0.3,
                    "invalid": 0.0,
                }
            },
            "defaults": {
                "node_agent": {"default_model": None, "default_runtime": None},
                "match_engine": {"allow_generic_jobs": True}
            }
        }
    
    @property
    def model_families(self) -> Dict:
        """Get model families config / 获取模型家族配置"""
        return self._config.get("model_families", {})
    
    @property
    def compatibility_config(self) -> Dict:
        """Get compatibility config / 获取兼容性配置"""
        return self._config.get("compatibility", {})
    
    @property
    def defaults(self) -> Dict:
        """Get defaults config / 获取默认配置"""
        return self._config.get("defaults", {})
    
    @property
    def runtimes(self) -> Dict:
        """Get runtimes config / 获取运行时配置"""
        return self._config.get("runtimes", {})
    
    def get_scores(self) -> Dict[CompatibilityLevel, float]:
        """
        Get compatibility score mapping
        获取兼容性评分映射
        """
        weights = self.compatibility_config.get("scoring_weights", {})
        return {
            CompatibilityLevel.EXACT: weights.get("exact_match", 1.0),
            CompatibilityLevel.FAMILY: weights.get("family_match", 0.8),
            CompatibilityLevel.COMPATIBLE: weights.get("compatible", 0.6),
            CompatibilityLevel.CROSS_FAMILY: weights.get("cross_family", 0.3),
            CompatibilityLevel.INVALID: weights.get("invalid", 0.0),
        }
    
    def get_family(self, model_name: str) -> Optional[str]:
        """
        Extract family from model name
        从模型名推断家族
        """
        model_lower = model_name.lower()
        
        for family in self.model_families.keys():
            if model_lower.startswith(family):
                return family
        
        return None
    
    def is_model_in_family(self, model_name: str, family: str) -> bool:
        """
        Check if model belongs to specified family
        检查模型是否属于指定家族
        """
        return self.get_family(model_name) == family.lower()
    
    def reload(self):
        """Reload configuration / 重新加载配置"""
        self._load_config()


# Global singleton instance
model_config = ModelConfig()


class ModelVersion:
    """
    Model Version Parser
    模型版本解析器
    
    Parses model names like:
    - qwen2.5:7b -> family=qwen, major=2, minor=5, suffix=7b
    - llama3-8b -> family=llama, major=3, minor=0, suffix=8b
    """
    
    def __init__(self, family: str, major: int, minor: int, suffix: str = ""):
        self.family = family.lower()
        self.major = major
        self.minor = minor
        self.suffix = suffix.lower()
    
    @property
    def full_version(self) -> float:
        """Get full version number / 获取完整版本号"""
        return float(f"{self.major}.{self.minor}")
    
    def can_serve(self, required: "ModelVersion", config: ModelConfig) -> bool:
        """
        Check if this model can serve the required model
        检查此模型是否可服务 required 模型
        
        Rules:
        - Same family
        - Version >= required (support downgrade)
        - Size >= required (can only serve smaller)
        """
        if self.family != required.family:
            return False
        
        # Version check (higher version can serve lower)
        if self.full_version < required.full_version:
            return False
        
        # Size check (larger can serve smaller)
        if self.get_size_rank(config) < required.get_size_rank(config):
            return False
        
        return True
    
    def get_size_rank(self, config: ModelConfig) -> int:
        """
        Get size rank (ascending order)
        获取 Size 排名（从小到大）
        """
        # Get size order from config
        size_order = config.compatibility_config.get("size_order", {})
        ascending = size_order.get("ascending", [])
        embedding = size_order.get("embedding", [])
        
        all_sizes = {s: i for i, s in enumerate(ascending)}
        all_sizes.update({s: i for i, s in enumerate(embedding)})
        
        return all_sizes.get(self.suffix, 5)  # Default rank 5


def parse_model_name(name: str) -> ModelVersion:
    """
    Parse model name into ModelVersion
    解析模型名称为 ModelVersion
    
    Supported formats:
    - qwen2.5:7b -> family=qwen, major=2, minor=5, suffix=7b
    - qwen2.5-7b -> family=qwen, major=2, minor=5, suffix=7b
    - qwen3.5:latest -> family=qwen, major=3, minor=5, suffix=latest
    - gemma4:e4b -> family=gemma, major=4, minor=0, suffix=e4b
    """
    name = name.lower().replace("-", ":")
    
    parts = name.split(":")
    version_part = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""
    
    # Match family + major.minor
    match = re.match(r'^([a-z]+)(\d+)\.?(\d*)$', version_part)
    if match:
        family = match.group(1)
        major = int(match.group(2))
        minor = int(match.group(3)) if match.group(3) else 0
    else:
        # Match family only
        match = re.match(r'^([a-z]+)', version_part)
        family = match.group(1) if match else version_part
        major, minor = 1, 0
    
    return ModelVersion(family=family, major=major, minor=minor, suffix=suffix)


class CompatibilityMatrix:
    """
    Model Compatibility Matrix - DCM v3.1 (Dynamic Config)
    模型兼容性矩阵（动态配置版）
    
    Matching rules (loaded from config):
    1. EXACT = 1.0 (exact match)
    2. FAMILY = 0.8 (same family + version/size satisfied)
    3. COMPATIBLE = 0.6 (compatible model)
    4. CROSS_FAMILY = 0.3 (cross-family)
    5. INVALID = 0.0 (invalid)
    
    Version coverage rules:
    - 4.0 → 3.5 → 3.0 → 2.5 → 2.0 (downgrade supported)
    - 14b → 7b → 2b (larger can serve smaller)
    """
    
    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or model_config
    
    def get_compatibility(self, job_model: Optional[str], slot_model: str) -> float:
        """
        Get compatibility score
        获取兼容性评分
        """
        level = self.get_compatibility_level(job_model, slot_model)
        scores = self.config.get_scores()
        return scores.get(level, 0.0)
    
    def get_compatibility_level(
        self,
        job_model: Optional[str],
        slot_model: str
    ) -> CompatibilityLevel:
        """
        Get compatibility level
        获取兼容性等级
        """
        # Generic job (no model requirement)
        if not job_model:
            return CompatibilityLevel.FAMILY
        
        # Normalize names
        job_normalized = job_model.lower().replace("-", ":")
        slot_normalized = slot_model.lower().replace("-", ":")
        
        # EXACT Match
        if job_normalized == slot_normalized:
            return CompatibilityLevel.EXACT
        
        job_version = parse_model_name(job_model)
        slot_version = parse_model_name(slot_model)
        
        # Same family check
        if job_version.family == slot_version.family:
            if slot_version.can_serve(job_version, self.config):
                return CompatibilityLevel.FAMILY
            else:
                return CompatibilityLevel.INVALID
        
        # Cross-family compatibility check (optional feature)
        cross_config = self.config.compatibility_config.get("cross_family_compatible", {})
        if cross_config.get("enabled", False):
            if self._is_cross_family_compatible(job_version.family, slot_version.family):
                return CompatibilityLevel.COMPATIBLE
        
        # Cross-family
        return CompatibilityLevel.CROSS_FAMILY
    
    def _is_cross_family_compatible(self, family1: str, family2: str) -> bool:
        """
        Check cross-family compatibility
        检查跨家族兼容性
        """
        cross_config = self.config.compatibility_config.get("cross_family_compatible", {})
        pairs = cross_config.get("pairs", [])
        
        for pair in pairs:
            if family1 in pair and family2 in pair:
                return True
        
        return False
    
    def get_match_reason(self, job_model: str, slot_model: str) -> str:
        """
        Get match reason description
        获取匹配原因描述
        """
        level = self.get_compatibility_level(job_model, slot_model)
        scores = self.config.get_scores()
        score = scores.get(level, 0.0)
        
        reasons = {
            CompatibilityLevel.EXACT: f"Exact match {job_model} == {slot_model}",
            CompatibilityLevel.FAMILY: f"Family match {slot_model} can serve {job_model}",
            CompatibilityLevel.COMPATIBLE: f"Compatible model {slot_model} compatible with {job_model}",
            CompatibilityLevel.CROSS_FAMILY: f"Cross-family {slot_model} vs {job_model}",
            CompatibilityLevel.INVALID: f"Invalid {slot_model} cannot serve {job_model}",
        }
        
        reason = reasons.get(level, "Unknown")
        return f"{reason} (score: {score})"
    
    def is_job_model_supported(
        self,
        job_model: Optional[str],
        slot_model: str
    ) -> bool:
        """
        Check if job model is supported by slot
        检查 Job 模型是否被 Slot 支持
        """
        if not job_model:
            return True  # Generic job
        
        level = self.get_compatibility_level(job_model, slot_model)
        return level in {
            CompatibilityLevel.EXACT,
            CompatibilityLevel.FAMILY,
            CompatibilityLevel.COMPATIBLE,
        }


# Global singleton instance
compatibility_matrix = CompatibilityMatrix()


# Test / 测试
if __name__ == "__main__":
    print("=== DCM v3.1 Compatibility Test ===")
    print(f"Config loaded: {model_config._config is not None}")
    print(f"Model families: {list(model_config.model_families.keys())}")
    print()
    
    matrix = CompatibilityMatrix()
    
    test_cases = [
        # (job_model, slot_model, expected_level, expected_score)
        ("qwen2.5:7b", "qwen2.5:7b", CompatibilityLevel.EXACT, 1.0),
        ("qwen2.5:7b", "qwen3.5:7b", CompatibilityLevel.FAMILY, 0.8),
        ("qwen2.5:7b", "qwen2.5:14b", CompatibilityLevel.FAMILY, 0.8),
        ("qwen2.5:7b", "qwen2.5:2b", CompatibilityLevel.INVALID, 0.0),
        ("qwen3.5:7b", "qwen2.5:7b", CompatibilityLevel.INVALID, 0.0),
        (None, "qwen2.5:7b", CompatibilityLevel.FAMILY, 0.8),
        ("llama3:8b", "llama3.2:8b", CompatibilityLevel.FAMILY, 0.8),
        ("gemma4:e4b", "gemma4:e9b", CompatibilityLevel.FAMILY, 0.8),
    ]
    
    all_passed = True
    for job, slot, expected_level, expected_score in test_cases:
        actual_level = matrix.get_compatibility_level(job, slot)
        actual_score = matrix.get_compatibility(job, slot)
        
        status = "✓" if actual_level == expected_level and abs(actual_score - expected_score) < 0.01 else "✗"
        if status == "✗":
            all_passed = False
        
        print(f"{status} {str(job or 'generic'):15} -> {slot:15} | {actual_level.value:12} ({actual_score:.2f})")
    
    print()
    print(f"All tests passed: {all_passed}")
