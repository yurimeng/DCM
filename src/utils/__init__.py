"""
DCM - Utilities
"""

import hashlib
import base64


def hash_result(result: str) -> str:
    """计算结果的 SHA256 哈希"""
    return hashlib.sha256(result.encode()).hexdigest()


def encode_base64(data: str) -> str:
    """Base64 编码"""
    return base64.b64encode(data.encode()).decode()


def decode_base64(data: str) -> str:
    """Base64 解码"""
    return base64.b64decode(data.encode()).decode()


__all__ = [
    "hash_result",
    "encode_base64",
    "decode_base64",
]
