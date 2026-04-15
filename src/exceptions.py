"""
DCM 异常定义 - 简化版

统一管理业务异常和错误消息，便于:
1. 错误消息集中管理
2. 错误码统一
3. 错误统计和分析

使用方式:
    from src.exceptions import (
        ErrorCode,
        HTTPException,
        raise_not_found,
        raise_bad_request,
    )
    
    # 方式1: 使用快捷函数
    if not job:
        raise_not_found("job", job_id)
    
    # 方式2: 使用 ErrorCode
    raise HTTPException(status_code=404, detail={
        "code": ErrorCode.NOT_FOUND,
        "message": "Job not found",
        "resource": "job",
        "id": job_id,
    })
"""

from enum import Enum
from typing import Optional, Any, Dict
from fastapi import HTTPException as FastAPIHTTPException


# =============================================================================
# 错误码枚举
# =============================================================================

class ErrorCode(str, Enum):
    """
    DCM 错误码枚举
    
    命名规范:
        - NOT_FOUND: 资源不存在
        - INVALID_STATUS: 状态不合法
        - VALIDATION_ERROR: 验证错误
        - DUPLICATE: 重复操作
        - UNAUTHORIZED: 未授权
        - FORBIDDEN: 禁止访问
        - RATE_LIMITED: 限流
        - INTERNAL_ERROR: 内部错误
        - SERVICE_UNAVAILABLE: 服务不可用
    """
    
    # ========== 4xx 客户端错误 ==========
    
    # 资源不存在
    NOT_FOUND = "NOT_FOUND"
    
    # 状态不合法
    INVALID_STATUS = "INVALID_STATUS"
    
    # 验证错误
    VALIDATION_ERROR = "VALIDATION_ERROR"
    
    # 重复操作
    DUPLICATE = "DUPLICATE"
    
    # 参数错误
    INVALID_PARAMETER = "INVALID_PARAMETER"
    
    # 未授权
    UNAUTHORIZED = "UNAUTHORIZED"
    
    # 禁止访问
    FORBIDDEN = "FORBIDDEN"
    
    # 限流
    RATE_LIMITED = "RATE_LIMITED"
    
    # 资源已存在
    ALREADY_EXISTS = "ALREADY_EXISTS"
    
    # 余额不足
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    
    # Stake 不足
    INSUFFICIENT_STAKE = "INSUFFICIENT_STAKE"
    
    # 操作超时
    TIMEOUT = "TIMEOUT"
    
    # ========== 5xx 服务端错误 ==========
    
    # 内部错误
    INTERNAL_ERROR = "INTERNAL_ERROR"
    
    # 服务不可用
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    
    # 数据库错误
    DATABASE_ERROR = "DATABASE_ERROR"
    
    # 队列错误
    QUEUE_ERROR = "QUEUE_ERROR"
    
    # 区块链错误
    BLOCKCHAIN_ERROR = "BLOCKCHAIN_ERROR"


# =============================================================================
# HTTP 异常类（增强版）
# =============================================================================

class HTTPException(FastAPIHTTPException):
    """
    增强版 HTTPException
    
    支持更丰富的错误信息结构:
    {
        "code": "NOT_FOUND",
        "message": "Job not found",
        "resource": "job",
        "id": "job_xxx"
    }
    """
    
    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        resource: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            status_code: HTTP 状态码
            code: 错误码
            message: 错误消息
            resource: 资源类型 (job, match, escrow, node, user)
            resource_id: 资源 ID
            details: 额外详情
        """
        detail = {
            "code": code.value if isinstance(code, ErrorCode) else code,
            "message": message,
        }
        
        if resource:
            detail["resource"] = resource
        if resource_id:
            detail["id"] = resource_id
        if details:
            detail["details"] = details
        
        super().__init__(status_code=status_code, detail=detail)


# =============================================================================
# 资源类型枚举
# =============================================================================

class ResourceType(str, Enum):
    """资源类型"""
    JOB = "job"
    MATCH = "match"
    ESCROW = "escrow"
    NODE = "node"
    USER = "user"
    CLUSTER = "cluster"
    DISPUTE = "dispute"
    STAKE = "stake"
    WALLET = "wallet"


# =============================================================================
# 快捷异常函数
# =============================================================================

def raise_not_found(
    resource: str,
    resource_id: str,
    status_code: int = 404,
) -> None:
    """
    抛出资源不存在异常
    
    Args:
        resource: 资源类型 (job, match, escrow, node, user)
        resource_id: 资源 ID
        status_code: HTTP 状态码 (默认 404)
    """
    message = f"{resource.capitalize()} not found"
    raise HTTPException(
        status_code=status_code,
        code=ErrorCode.NOT_FOUND,
        message=message,
        resource=resource,
        resource_id=resource_id,
    )


def raise_invalid_status(
    resource: str,
    resource_id: str,
    current_status: str,
    expected_status: Optional[str] = None,
    status_code: int = 400,
) -> None:
    """
    抛出状态不合法异常
    
    Args:
        resource: 资源类型
        resource_id: 资源 ID
        current_status: 当前状态
        expected_status: 期望状态
        status_code: HTTP 状态码 (默认 400)
    """
    if expected_status:
        message = f"{resource} status must be {expected_status}, got {current_status}"
    else:
        message = f"Invalid {resource} status: {current_status}"
    
    raise HTTPException(
        status_code=status_code,
        code=ErrorCode.INVALID_STATUS,
        message=message,
        resource=resource,
        resource_id=resource_id,
        details={"current_status": current_status, "expected_status": expected_status},
    )


def raise_validation_error(
    message: str,
    field: Optional[str] = None,
    status_code: int = 422,
) -> None:
    """
    抛出验证错误异常
    
    Args:
        message: 错误消息
        field: 字段名
        status_code: HTTP 状态码 (默认 422)
    """
    raise HTTPException(
        status_code=status_code,
        code=ErrorCode.VALIDATION_ERROR,
        message=message,
        details={"field": field} if field else None,
    )


def raise_duplicate(
    resource: str,
    resource_id: str,
    status_code: int = 409,
) -> None:
    """
    抛出重复操作异常
    
    Args:
        resource: 资源类型
        resource_id: 资源 ID
        status_code: HTTP 状态码 (默认 409)
    """
    message = f"{resource.capitalize()} already exists"
    raise HTTPException(
        status_code=status_code,
        code=ErrorCode.DUPLICATE,
        message=message,
        resource=resource,
        resource_id=resource_id,
    )


def raise_bad_request(
    message: str,
    code: ErrorCode = ErrorCode.INVALID_PARAMETER,
    details: Optional[Dict[str, Any]] = None,
    status_code: int = 400,
) -> None:
    """
    抛出通用请求错误异常
    
    Args:
        message: 错误消息
        code: 错误码
        details: 额外详情
        status_code: HTTP 状态码 (默认 400)
    """
    raise HTTPException(
        status_code=status_code,
        code=code,
        message=message,
        details=details,
    )


def raise_unauthorized(
    message: str = "Unauthorized",
    status_code: int = 401,
) -> None:
    """
    抛出未授权异常
    
    Args:
        message: 错误消息
        status_code: HTTP 状态码 (默认 401)
    """
    raise HTTPException(
        status_code=status_code,
        code=ErrorCode.UNAUTHORIZED,
        message=message,
    )


def raise_forbidden(
    message: str = "Forbidden",
    status_code: int = 403,
) -> None:
    """
    抛出禁止访问异常
    
    Args:
        message: 错误消息
        status_code: HTTP 状态码 (默认 403)
    """
    raise HTTPException(
        status_code=status_code,
        code=ErrorCode.FORBIDDEN,
        message=message,
    )


def raise_internal_error(
    message: str = "Internal server error",
    details: Optional[Dict[str, Any]] = None,
    status_code: int = 500,
) -> None:
    """
    抛出内部错误异常
    
    Args:
        message: 错误消息
        details: 额外详情
        status_code: HTTP 状态码 (默认 500)
    """
    raise HTTPException(
        status_code=status_code,
        code=ErrorCode.INTERNAL_ERROR,
        message=message,
        details=details,
    )


# =============================================================================
# 辅助函数
# =============================================================================

def get_error_response(
    code: ErrorCode,
    message: str,
    resource: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    构建标准错误响应
    
    Returns:
        错误响应字典
    """
    response = {
        "code": code.value if isinstance(code, ErrorCode) else code,
        "message": message,
    }
    
    if resource:
        response["resource"] = resource
    if resource_id:
        response["id"] = resource_id
    if details:
        response["details"] = details
    
    return response


# =============================================================================
# 状态码映射
# =============================================================================

STATUS_CODE_MAP = {
    # 4xx
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.INVALID_STATUS: 400,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.DUPLICATE: 409,
    ErrorCode.INVALID_PARAMETER: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.ALREADY_EXISTS: 409,
    ErrorCode.INSUFFICIENT_BALANCE: 400,
    ErrorCode.INSUFFICIENT_STAKE: 400,
    ErrorCode.TIMEOUT: 408,
    # 5xx
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.DATABASE_ERROR: 500,
    ErrorCode.QUEUE_ERROR: 500,
    ErrorCode.BLOCKCHAIN_ERROR: 500,
}


def get_status_code(code: ErrorCode) -> int:
    """
    根据错误码获取 HTTP 状态码
    
    Args:
        code: 错误码
        
    Returns:
        HTTP 状态码
    """
    return STATUS_CODE_MAP.get(code, 500)
