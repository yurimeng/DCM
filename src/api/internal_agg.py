"""
Internal API - 聚合入口

按功能拆分为多个子模块:
- operations: 运维接口 (健康检查、配置)
- matching: 撮合/验证/结算接口
- reconciliation: 对账接口
- admin: 管理接口 (Stake、统计、数据库)
- debug: 调试接口 (仅开发环境)

⚠️ 注意:
- debug 模块仅用于开发/调试，生产环境应禁用
- 所有接口路径保持不变，向后兼容
"""

from fastapi import APIRouter

# 导入子模块路由
from .internal import (
    operations_router,
    matching_router,
    reconciliation_router,
    admin_router,
    debug_router,
)

# 创建主路由
router = APIRouter(prefix="/internal/v1", tags=["internal"])

# 挂载子路由
router.include_router(operations_router)
router.include_router(matching_router)
router.include_router(reconciliation_router)
router.include_router(admin_router)
router.include_router(debug_router)


# ============================================================================
# 路由汇总（供参考）
# ============================================================================
# 
# operations (4):
#   GET  /internal/v1/health
#   GET  /internal/v1/config/job
#   POST /internal/v1/config/job/reload
#   GET  /internal/v1/runtimes
#
# matching (6):
#   POST /internal/v1/match/trigger
#   POST /internal/v1/match/poll
#   POST /internal/v1/verify
#   POST /internal/v1/verify/layer2
#   POST /internal/v1/settlement/execute
#   POST /internal/v1/retry/handle
#
# reconciliation (3):
#   GET  /internal/v1/nodes/orphans
#   GET  /internal/v1/reconciliation/check
#   GET  /internal/v1/reconciliation/verify/{job_id}
#
# admin (6):
#   POST /internal/v1/stake/freeze
#   GET  /internal/v1/disputes/{dispute_id}
#   GET  /internal/v1/stats/failures
#   GET  /internal/v1/stats/verification
#   GET  /internal/v1/debug/db-status
#   POST /internal/v1/db/migrate
#   GET  /internal/v1/db/check/{table}
#
# debug (6):
#   POST /internal/v1/debug/node-login
#   POST /internal/v1/debug/test-status-store
#   POST /internal/v1/debug/test-node-login-full
#   POST /internal/v1/debug/test-login-request
#   POST /internal/v1/debug/node-login-simple
#
# 总计: 25 个接口
# ============================================================================
