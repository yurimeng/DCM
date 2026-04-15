"""
Internal API - 调试接口

⚠️ 警告: 这些接口仅用于开发/调试，生产环境应禁用

包含: 节点登录测试、状态存储测试
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any

from ...database import get_db
from ...repositories import UserRepository, NodeRepository

router = APIRouter(prefix="", tags=["internal/debug"])


# ⚠️ 警告: 以下接口仅用于开发/调试，生产环境应禁用


@router.post("/debug/node-login")
async def debug_node_login(
    node_id: str,
    user_id: str,
    db: Session = Depends(get_db)
):
    """调试: 模拟 node_login"""
    import traceback
    
    result = {}
    
    # 1. Check user
    try:
        user_repo = UserRepository(db)
        is_valid, user_db, error_msg = user_repo.validate_user_id(user_id)
        result["user_valid"] = is_valid
        result["user_error"] = error_msg
    except Exception as e:
        result["user_error"] = str(e)
        result["user_trace"] = traceback.format_exc()
        return {"error": result}
    
    # 2. Check node
    try:
        node_repo = NodeRepository(db)
        db_node = node_repo.get(node_id)
        result["node_found"] = db_node is not None
        if db_node:
            result["node_user_id"] = db_node.user_id
            result["node_cluster_id"] = db_node.cluster_id
            result["node_cluster_id_type"] = type(db_node.cluster_id).__name__
            result["node_runtime"] = db_node.runtime
            result["node_runtime_type"] = type(db_node.runtime).__name__
    except Exception as e:
        result["node_error"] = str(e)
        result["node_trace"] = traceback.format_exc()
    
    # 3. Test return value
    try:
        import time
        return_value = {
            "node_id": node_id,
            "status": "ok",
            "cluster_id": db_node.cluster_id,
            "timestamp": int(time.time() * 1000),
        }
        result["return_value"] = return_value
    except Exception as e:
        result["return_error"] = str(e)
        result["return_trace"] = traceback.format_exc()
    
    # 4. Simulate full node_login endpoint
    try:
        from ...api.nodes import node_login
        import inspect
        sig = inspect.signature(node_login)
        result["node_login_sig"] = str(sig)
        result["node_login_found"] = True
    except Exception as e:
        result["node_login_error"] = str(e)
        result["node_login_trace"] = traceback.format_exc()
    
    return result


@router.post("/debug/test-status-store")
async def debug_test_status_store(
    node_id: str,
    db: Session = Depends(get_db)
):
    """测试 NodeStatusStore"""
    from ...services.node_status_store import update_node_status, get_node_info
    import traceback
    import time
    
    result = {"node_id": node_id}
    
    # Test update_node_status
    try:
        live_status = {
            "timestamp": int(time.time() * 1000),
            "status": {"state": "idle", "vram_used_gb": 0, "vram_total_gb": 24},
            "capacity": {"max_concurrency_total": 2, "max_concurrency_available": 2},
            "load": {"active_jobs": 0, "available_token_capacity": 100000},
        }
        update_node_status(node_id, live_status)
        result["update_status"] = "ok"
    except Exception as e:
        result["update_status"] = "error"
        result["update_error"] = str(e)
        result["update_trace"] = traceback.format_exc()
    
    # Test get_node_info
    try:
        info = get_node_info(node_id)
        result["get_info"] = "ok"
        result["node_info"] = info
    except Exception as e:
        result["get_info"] = "error"
        result["get_error"] = str(e)
        result["get_trace"] = traceback.format_exc()
    
    return result


@router.post("/debug/test-node-login-full")
async def debug_test_node_login_full(
    node_id: str,
    user_id: str,
    db: Session = Depends(get_db)
):
    """完整测试 node_login 的每个步骤"""
    import traceback
    import time
    
    steps = []
    
    # Step 1: Validate user
    try:
        user_repo = UserRepository(db)
        is_valid, user_db, error_msg = user_repo.validate_user_id(user_id)
        steps.append({
            "step": 1,
            "name": "validate_user",
            "success": is_valid,
            "error": error_msg
        })
    except Exception as e:
        steps.append({"step": 1, "name": "validate_user", "success": False, "error": str(e), "trace": traceback.format_exc()})
        return {"steps": steps}
    
    # Step 2: Get node
    try:
        node_repo = NodeRepository(db)
        db_node = node_repo.get(node_id)
        steps.append({
            "step": 2,
            "name": "get_node",
            "success": db_node is not None,
            "node_found": db_node is not None,
            "node_user_id": db_node.user_id if db_node else None
        })
    except Exception as e:
        steps.append({"step": 2, "name": "get_node", "success": False, "error": str(e), "trace": traceback.format_exc()})
        return {"steps": steps}
    
    # Step 3: Check user match
    try:
        user_match = db_node.user_id == user_id
        steps.append({
            "step": 3,
            "name": "check_user_match",
            "success": user_match,
            "db_node_user_id": db_node.user_id,
            "input_user_id": user_id
        })
    except Exception as e:
        steps.append({"step": 3, "name": "check_user_match", "success": False, "error": str(e), "trace": traceback.format_exc()})
        return {"steps": steps}
    
    # Step 4: Build return value
    try:
        result = {
            "node_id": node_id,
            "status": "ok",
            "cluster_id": db_node.cluster_id,
            "timestamp": int(time.time() * 1000),
        }
        steps.append({"step": 4, "name": "build_return", "success": True, "result": result})
        return {"steps": steps, "final_result": result}
    except Exception as e:
        steps.append({"step": 4, "name": "build_return", "success": False, "error": str(e), "trace": traceback.format_exc()})
        return {"steps": steps}


@router.post("/debug/test-login-request")
async def test_login_request(
    node_id: str,
    body: dict,
    db: Session = Depends(get_db)
):
    """测试不同格式的 login 请求"""
    return {
        "received_node_id": node_id,
        "received_body": body,
        "body_type": str(type(body)),
        "body_keys": list(body.keys()) if isinstance(body, dict) else [],
    }


@router.post("/debug/node-login-simple")
async def debug_node_login_simple(
    node_id: str,
    body: dict,
    db: Session = Depends(get_db)
):
    """简化版 node_login 调试"""
    import time
    from ...repositories import UserRepository, NodeRepository
    
    user_id = body.get("user_id") if body else None
    
    # 简化逻辑
    if not user_id:
        return {"error": "missing user_id"}
    
    user_repo = UserRepository(db)
    is_valid, _, _ = user_repo.validate_user_id(user_id)
    if not is_valid:
        return {"error": "invalid user"}
    
    node_repo = NodeRepository(db)
    db_node = node_repo.get(node_id)
    
    if not db_node:
        return {"error": "node not found"}
    
    return {
        "node_id": node_id,
        "status": "ok",
        "cluster_id": db_node.cluster_id,
        "timestamp": int(time.time() * 1000),
    }
