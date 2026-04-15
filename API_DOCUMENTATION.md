# DCM API 接口总览文档

> **项目**: Decentralized Compute Market - 去中心化 AI 推理市场
> **版本**: v3.2 | **更新日期**: 2026-04-15

---

## 📁 目录结构

```
DCM/
├── src/
│   ├── api/              # API 端点层
│   │   ├── jobs.py       # Job 管理
│   │   ├── nodes.py      # Node 管理
│   │   ├── users.py      # 用户管理
│   │   ├── wallet.py     # 钱包管理
│   │   ├── disputes.py   # 争议处理
│   │   ├── core.py       # Core Cluster
│   │   ├── internal.py   # 内部 API
│   │   ├── quic.py       # 推理请求
│   │   ├── relay.py       # Relay 服务
│   │   ├── p2p.py        # P2P 网络
│   │   ├── scaler.py     # 扩缩容
│   │   └── worker_pool.py # Worker 池
│   │
│   ├── services/          # 业务服务层
│   │   ├── matching.py    # 撮合引擎
│   │   ├── node_status_store.py  # 节点状态存储
│   │   ├── escrow.py     # Escrow 服务
│   │   ├── verification.py  # 结果验证
│   │   ├── settlement_config.py  # 结算配置
│   │   ├── retry.py      # 重试机制
│   │   ├── pre_lock.py   # Pre-Lock 机制
│   │   ├── stake.py      # Stake 管理
│   │   ├── hard_filter.py  # 硬过滤
│   │   ├── scoring.py    # 评分服务
│   │   ├── cluster_builder.py  # Cluster 构建
│   │   └── queue/        # Job Queue
│   │
│   ├── models/           # 数据模型
│   │   ├── job.py        # Job 模型
│   │   ├── node.py       # Node 模型
│   │   ├── cluster.py    # Cluster 模型
│   │   ├── match.py      # Match 模型
│   │   ├── escrow.py     # Escrow 模型
│   │   ├── user.py       # 用户模型
│   │   └── db_models.py  # 数据库模型
│   │
│   ├── core/             # Core 系统
│   │   ├── cluster/      # Core 集群
│   │   ├── p2p/          # P2P 网络
│   │   ├── quic/          # QUIC 传输
│   │   └── relay/         # Relay 服务
│   │
│   ├── repositories.py    # 数据访问层
│   ├── database.py        # 数据库配置
│   └── main.py            # FastAPI 入口
│
└── tests/                 # 测试
```

---

## 🔌 API 端点总览

### 1. Jobs API (`/api/v1/jobs`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| POST | `/api/v1/jobs` | 提交 Job (DCM 格式) | `_create_job_and_match()` |
| POST | `/api/v1/jobs/openai` | 提交 Job (OpenAI 兼容) | `_create_job_and_match()` |
| GET | `/api/v1/jobs/{job_id}` | 获取 Job 详情 | `JobRepository.get()` |
| GET | `/api/v1/jobs` | 列出 Job 列表 | `JobRepository.list_*()` |
| POST | `/api/v1/jobs/{job_id}/cancel` | 取消 Job | - |
| POST | `/api/v1/jobs/{job_id}/result` | 提交结果 | `Node.result_submit()` |
| GET | `/api/v1/jobs/{job_id}/escrow` | 获取 Escrow 状态 | `EscrowRepository.get_by_job()` |
| POST | `/api/v1/jobs/{job_id}/escrow/cancel` | 取消 Escrow | - |
| POST | `/api/v1/jobs/{job_id}/escrow/settle` | 手动结算 Escrow | - |
| POST | `/api/v1/jobs/{job_id}/prelock` | Pre-lock Job | - |
| POST | `/api/v1/jobs/{job_id}/prelock/ack` | Pre-lock ACK | - |
| POST | `/api/v1/jobs/{job_id}/prelock/release` | 释放 Pre-lock | - |
| GET | `/api/v1/jobs/stats/summary` | 获取统计 | - |
| GET | `/api/v1/jobs/debug/matching-status` | 调试：匹配状态 | - |

---

### 2. Nodes API (`/api/v1/nodes`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| POST | `/api/v1/nodes` | 注册 Node | `NodeRepository.create()` |
| GET | `/api/v1/nodes/{node_id}` | 获取 Node 详情 | `NodeRepository.get()` |
| POST | `/api/v1/nodes/{node_id}/online` | 节点上线 | `matching_service.poll_node()` |
| POST | `/api/v1/nodes/{node_id}/offline` | 节点下线 | `NodeRepository.update()` |
| POST | `/api/v1/nodes/{node_id}/poll` | 节点拉取 Job | `matching_service.poll_node()` |
| POST | `/api/v1/nodes/{node_id}/live_status` | 上报实时状态 | `update_node_status()` |
| POST | `/api/v1/nodes/{node_id}/capacity_report` | 上报容量信息 | `update_node_status()` |
| POST | `/api/v1/nodes/{node_id}/stake/deposit` | 质押存款 | `StakeService.deposit_stake()` |
| GET | `/api/v1/nodes/{node_id}/status` | 获取节点状态 | - |
| GET | `/api/v1/nodes` | 列出节点列表 | `NodeRepository.list_all()` |
| DELETE | `/api/v1/nodes/{node_id}` | 删除节点 | `NodeRepository.delete()` |
| GET | `/api/v1/nodes/debug/matching-status` | 调试：匹配状态 | - |

---

### 3. Users API (`/api/v1/users`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| POST | `/api/v1/users/register` | 用户注册 | `UserRepository.create()` |
| POST | `/api/v1/users/login` | 用户登录 | `UserRepository.validate_user_id()` |
| GET | `/api/v1/users/{user_id}` | 获取用户信息 | `UserRepository.get()` |

**内部方法**:
- `create_access_token()` - 创建访问令牌
- `verify_token()` - 验证令牌
- `get_current_user()` - 获取当前用户 (Depends)
- `get_optional_user()` - 可选获取当前用户 (Depends)

---

### 4. Wallet API (`/api/v1/wallet`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| POST | `/api/v1/wallet/initialize` | 初始化测试钱包 | `wallet_service.initialize_test_accounts()` |
| POST | `/api/v1/wallet/accounts` | 创建账户 | `wallet_service.create_account()` |
| GET | `/api/v1/wallet/accounts` | 列出账户 | `wallet_service.get_all_accounts()` |
| GET | `/api/v1/wallet/accounts/{account_id}` | 获取账户详情 | `wallet_service.get_account()` |
| GET | `/api/v1/wallet/accounts/{account_id}/balance` | 获取余额 | `wallet_service.get_balance()` |
| GET | `/api/v1/wallet/accounts/{account_id}/transactions` | 获取交易历史 | - |
| POST | `/api/v1/wallet/transfer` | 转账 | `wallet_service.transfer()` |
| POST | `/api/v1/wallet/escrow/lock` | 锁定 Escrow | `wallet_service.escrow_lock()` |
| POST | `/api/v1/wallet/escrow/release` | 释放 Escrow | `wallet_service.escrow_release()` |
| POST | `/api/v1/wallet/escrow/settle` | 结算 Escrow | `wallet_service.escrow_settle()` |
| POST | `/api/v1/wallet/stake/deposit` | Stake 存款 | `wallet_service.stake_deposit()` |
| GET | `/api/v1/wallet/stats` | 获取统计 | `wallet_service.get_stats()` |

---

### 5. Disputes API (`/api/v1/disputes`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| GET | `/api/v1/disputes/{dispute_id}` | 获取争议详情 | `StakeService.get_dispute()` |
| GET | `/api/v1/disputes/node/{node_id}` | 获取节点争议 | - |
| GET | `/api/v1/disputes` | 列出争议列表 | - |
| POST | `/api/v1/disputes/{dispute_id}/appeals` | 提交申诉 | - |
| GET | `/api/v1/disputes/{dispute_id}/appeals/{appeal_id}` | 获取申诉详情 | - |
| GET | `/api/v1/disputes/appeals` | 列出申诉列表 | - |
| GET | `/api/v1/disputes/stats/summary` | 获取统计 | - |

---

### 6. Core Cluster API (`/api/v1/core`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| GET | `/api/v1/core/nodes` | 获取节点列表 | `cluster_service.get_all_nodes()` |
| POST | `/api/v1/core/nodes/register` | 注册节点 | `cluster_service.register_node()` |
| POST | `/api/v1/core/nodes/{node_id}/heartbeat` | 节点心跳 | `cluster_service.heartbeat()` |
| DELETE | `/api/v1/core/nodes/{node_id}` | 移除节点 | `cluster_service.remove_node()` |
| GET | `/api/v1/core/health` | 获取健康状态 | - |
| POST | `/api/v1/core/sync` | P2P 同步数据 | `p2p_service.broadcast_*()` |
| GET | `/api/v1/core/select` | 选择节点 | `cluster_service.select_node()` |
| GET | `/api/v1/core/metrics` | 获取指标 | `cluster_service.get_metrics()` |
| GET | `/api/v1/core/quorum` | 检查多数节点 | `cluster_service.is_quorum_met()` |
| GET | `/api/v1/core/config` | 获取配置 | - |
| GET | `/api/v1/core/health_check` | 健康检查 | - |

---

### 7. Internal API (`/internal/v1`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| GET | `/internal/v1/health` | 健康检查 | - |
| GET | `/internal/v1/config/job` | 获取 Job 配置 | `get_job_config()` |
| POST | `/internal/v1/config/job/reload` | 重新加载配置 | `reload_job_config()` |
| GET | `/internal/v1/runtimes` | 获取支持的运行时 | - |
| POST | `/internal/v1/match/trigger` | 触发撮合 | `matching_service.trigger_match()` |
| POST | `/internal/v1/match/poll` | 节点拉取 | `matching_service.poll_node()` |
| POST | `/internal/v1/verify` | 验证结果 | `verification_service.verify_layer1()` |
| POST | `/internal/v1/verify/layer2` | Layer2 结果提交 | `verification_service.submit_layer2_result()` |
| POST | `/internal/v1/settlement/execute` | 执行结算 | `escrow_service._execute_settlement_internal()` |
| POST | `/internal/v1/retry/handle` | 处理重试 | `retry_service.handle_failure()` |
| POST | `/internal/v1/stake/freeze` | 冻结 Stake | `stake_service.freeze_stake()` |
| GET | `/internal/v1/disputes/{dispute_id}` | 获取争议 | `stake_service.get_dispute()` |
| GET | `/internal/v1/reconciliation/check` | 对账检查 | `chain_sync_service.reconcile()` |
| GET | `/internal/v1/reconciliation/verify/{job_id}` | 验证结算 | `chain_sync_service.verify_settlement()` |

---

### 8. Inference API (`/api/v1/inference`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| POST | `/api/v1/inference/execute` | 执行推理 | `quic_service.create_session()` |
| GET | `/api/v1/inference/status/{job_id}` | 获取状态 | `quic_service.get_status()` |
| GET | `/api/v1/inference/result/{job_id}` | 获取结果 | `quic_service.get_result()` |
| GET | `/api/v1/inference/sessions` | 列出会话 | `quic_service.get_all_sessions()` |
| GET | `/api/v1/inference/active` | 列出活跃会话 | `quic_service.get_active_sessions()` |
| POST | `/api/v1/inference/cancel/{job_id}` | 取消推理 | `quic_service.fail_inference()` |
| GET | `/api/v1/inference/metrics` | 获取指标 | `quic_service.get_metrics()` |
| GET | `/api/v1/inference/config` | 获取配置 | - |

---

### 9. Relay API (`/api/v1/relay`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| GET | `/api/v1/relay/status` | 获取状态 | `relay_service.get_status()` |
| GET | `/api/v1/relay/nodes` | 列出 Relay 节点 | `relay_service.get_all_relay_nodes()` |
| GET | `/api/v1/relay/nodes/{peer_id}` | 获取节点详情 | `relay_service.get_relay_node()` |
| POST | `/api/v1/relay/nodes/register` | 注册节点 | `relay_service.register_relay_node()` |
| DELETE | `/api/v1/relay/nodes/{peer_id}` | 取消注册 | `relay_service.unregister_relay_node()` |
| GET | `/api/v1/relay/diagnostics` | 诊断连接 | `relay_service.diagnose_connection()` |
| GET | `/api/v1/relay/connections` | 列出连接 | - |
| GET | `/api/v1/relay/capacity/{relay_node}` | 获取容量 | `relay_service.get_relay_node_capacity()` |
| GET | `/api/v1/relay/metrics` | 获取指标 | `relay_service.get_metrics()` |
| GET | `/api/v1/relay/config` | 获取配置 | - |

---

### 10. P2P API (`/api/v1/p2p`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| GET | `/api/v1/p2p/info` | 获取 P2P 信息 | `p2p_service.get_info()` |
| GET | `/api/v1/p2p/connections` | 获取连接状态 | `p2p_service.get_connections()` |
| GET | `/api/v1/p2p/status` | 获取状态 | `p2p_service.get_status()` |
| GET | `/api/v1/p2p/peers` | 列出节点 | `p2p_service.get_all_peers()` |
| POST | `/api/v1/p2p/peers/add` | 添加节点 | `p2p_service.add_peer()` |
| POST | `/api/v1/p2p/peers/connect` | 连接节点 | `p2p_service.connect_peer()` |
| POST | `/api/v1/p2p/peers/disconnect` | 断开节点 | `p2p_service.disconnect_peer()` |
| POST | `/api/v1/p2p/broadcast/job_update` | 广播 Job 更新 | `p2p_service.broadcast_job_update()` |
| POST | `/api/v1/p2p/broadcast/node_state` | 广播节点状态 | `p2p_service.broadcast_node_state()` |
| GET | `/api/v1/p2p/subscriptions` | 列出订阅 | - |
| GET | `/api/v1/p2p/metrics` | 获取指标 | `p2p_service.get_metrics()` |

---

### 11. Scaler API (`/api/v1/scaler`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| GET | `/api/v1/scaler/metrics` | 获取指标 | `scaler_service.get_current_metrics()` |
| GET | `/api/v1/scaler/status` | 获取状态 | `scaler_service.get_status()` |
| POST | `/api/v1/scaler/scale` | 手动扩缩 | `scaler_service.scale_up/down()` |
| POST | `/api/v1/scaler/scale/up` | 扩容 | `scaler_service.scale_up()` |
| POST | `/api/v1/scaler/scale/down` | 缩容 | `scaler_service.scale_down()` |
| GET | `/api/v1/scaler/workers` | 列出 Worker | `scaler_service.get_workers()` |
| GET | `/api/v1/scaler/workers/{worker_id}` | 获取 Worker 详情 | - |
| GET | `/api/v1/scaler/config` | 获取配置 | - |
| GET | `/api/v1/scaler/thresholds` | 获取阈值 | - |
| POST | `/api/v1/scaler/thresholds` | 更新阈值 | - |

---

### 12. Workers API (`/api/v1/workers`)

| 方法 | 路径 | 说明 | 服务方法 |
|------|------|------|----------|
| POST | `/api/v1/workers/register` | 注册 Worker | `worker_pool_service.register_worker()` |
| POST | `/api/v1/workers/{worker_id}/heartbeat` | Worker 心跳 | `worker_pool_service.heartbeat()` |
| POST | `/api/v1/workers/{worker_id}/drain` | 平滑下线 | `worker_pool_service.drain_worker()` |
| DELETE | `/api/v1/workers/{worker_id}` | 移除 Worker | `worker_pool_service.remove_worker()` |
| GET | `/api/v1/workers/` | 列出 Worker | `worker_pool_service.get_workers()` |
| GET | `/api/v1/workers/{worker_id}` | 获取 Worker 详情 | `worker_pool_service.get_worker()` |
| POST | `/api/v1/workers/dispatch/{worker_id}` | 分发请求 | `worker_pool_service.dispatch_request()` |
| POST | `/api/v1/workers/complete/{worker_id}` | 完成请求 | `worker_pool_service.complete_request()` |
| GET | `/api/v1/workers/select` | 选择 Worker | `worker_pool_service.select_worker()` |
| GET | `/api/v1/workers/network/redundancy` | 网络冗余状态 | - |
| POST | `/api/v1/workers/{worker_id}/reconnect` | 手动重连 | - |
| GET | `/api/v1/workers/status/pool` | 获取池状态 | - |

---

## 🛠️ Services 服务总览

### MatchingService (撮合引擎)

**位置**: `src/services/matching.py`

**核心方法**:

| 方法 | 说明 | 复杂度 |
|------|------|--------|
| `add_job(job: Job)` | 添加 Job 到队列 | O(1) |
| `remove_job(job_id: str)` | 从队列移除 Job | O(1) |
| `trigger_match(job_id: str)` | 触发撮合 | O(n) |
| `poll_node(node_id: str)` | 节点拉取 Job | O(n) |
| `get_match(match_id: str)` | 获取 Match | O(1) |
| `get_match_by_job(job_id: str)` | 根据 Job ID 获取 Match | O(1) |
| `release_node(node_id: str)` | 释放节点 | O(1) |
| `get_pending_jobs_count()` | 获取待撮合数量 | O(1) |
| `get_queue_stats()` | 获取队列统计 | O(1) |

**内部方法**:

| 方法 | 说明 |
|------|------|
| `_match(job: Job)` | 执行撮合逻辑 |
| `_can_match(job, node, node_status)` | 检查是否可以撮合 |
| `_create_match(job, node)` | 创建 Match |
| `_get_match_score(job, node)` | 计算匹配得分 |
| `_get_model_family(model_name)` | 获取模型家族 |

**属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `_matches` | `dict[str, Match]` | Match 记录表 |
| `_job_to_match` | `dict[str, str]` | Job → Match 映射 |
| `_node_jobs` | `dict[str, str]` | Node → Match 映射 |
| `_pending_jobs` | `dict[str, Job]` | 本地待撮合队列 |

---

### NodeStatusStore (节点状态存储)

**位置**: `src/services/node_status_store.py`

**核心方法**:

| 方法 | 说明 |
|------|------|
| `update(node_id, status)` | 更新节点状态 |
| `get(node_id)` | 获取原始状态 |
| `get_node_status(node_id)` | 获取解析后状态 |
| `delete(node_id)` | 删除节点状态 |
| `get_all()` | 获取所有状态 |
| `is_online(node_id, max_age_seconds)` | 检查是否在线 |
| `list_nodes(filter)` | 通用节点列表查询 |
| `list_online_nodes()` | 获取在线节点列表 |
| `get_node_info(node_id)` | 获取节点完整信息 |

**便捷函数**:

| 函数 | 说明 |
|------|------|
| `update_node_status(node_id, status, capacity_info)` | 更新状态 |
| `get_node_info(node_id)` | 获取节点信息 |
| `list_nodes(**kwargs)` | 获取节点列表 |
| `list_online_nodes(**kwargs)` | 获取在线节点列表 |

**支持后端**:
- `InMemoryNodeStatus` - 内存存储（单机）
- `RedisNodeStatus` - Redis 存储（分布式）

---

### EscrowService (Escrow 管理)

**位置**: `src/services/escrow.py`

**核心方法**:

| 方法 | 说明 |
|------|------|
| `create_escrow(job_id, bid_price, input_tokens, output_tokens_limit)` | 创建 Escrow |
| `get_escrow(job_id)` | 获取 Escrow |
| `get_all_escrows()` | 获取所有 Escrow |
| `complete_job(job_id)` | 标记为待结算 |
| `execute_settlement(request)` | 执行结算 |
| `manual_settle(job_id)` | 手动结算 |
| `cancel(job_id, reason, cancelled_by)` | 取消 Escrow |
| `refund(job_id, reason)` | 全额退款 |
| `get_pending_auto_complete()` | 获取待自动完成列表 |

**静态方法**:

| 方法 | 说明 |
|------|------|
| `_calculate_escrow(bid_price, input_tokens, output_tokens_limit)` | 计算锁定金额 |
| `_calculate_cost(locked_price, actual_tokens)` | 计算实际费用 |

---

### VerificationService (验证服务)

**位置**: `src/services/verification.py`

**核心方法**:

| 方法 | 说明 |
|------|------|
| `verify_layer1(match, job, result, result_hash, actual_latency_ms, actual_output_tokens)` | Layer1 验证 |
| `check_latency_penalty(job, actual_latency_ms)` | 检查延迟处罚 |
| `should_trigger_layer2()` | 判断是否触发 Layer2 |
| `trigger_layer2(match_id, job, original_result)` | 触发 Layer2 双跑 |
| `submit_layer2_result(layer2_job_id, second_result)` | 提交 Layer2 结果 |
| `record_violation(node_id)` | 记录违规 |
| `get_node_violations(node_id)` | 获取违规次数 |
| `reset_violations(node_id)` | 重置违规计数 |

**返回值**:

| 方法 | 返回 |
|------|------|
| `verify_layer1` | `(bool, str)` - 是否通过, 失败原因 |
| `check_latency_penalty` | `(bool, bool)` - 是否失败, 是否轻微超标 |
| `should_trigger_layer2` | `bool` - 是否触发 |
| `submit_layer2_result` | `(float, str)` - 相似度, 判定结果 |

---

### SettlementConfig (结算配置)

**位置**: `src/services/settlement_config.py`

**配置属性**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `platform_fee_rate` | `float` | 平台手续费比例 (默认 0.05) |
| `node_earn_rate` | `float` | 节点收入比例 (默认 0.95) |
| `escrow_buffer_multiplier` | `float` | Escrow 锁定倍数 (默认 1.1) |
| `escrow_auto_complete_seconds` | `int` | 自动完成延迟 (默认 60) |
| `escrow_allow_cancellation` | `bool` | 允许取消 |
| `min_bid_price` | `float` | 最小报价 |
| `layer2_sample_rate` | `float` | Layer2 抽样比例 (默认 0.1) |
| `latency_threshold_good` | `int` | 良好延迟阈值 (ms) |
| `latency_threshold_mild` | `int` | 可接受延迟阈值 (ms) |
| `similarity_threshold_high` | `float` | 高相似度阈值 |
| `similarity_threshold_low` | `float` | 低相似度阈值 |
| `stake_personal` | `float` | 个人节点 Stake |
| `stake_professional` | `float` | 专业节点 Stake |
| `stake_enterprise` | `float` | 企业节点 Stake |

**计算方法**:

| 方法 | 说明 |
|------|------|
| `calculate_platform_fee(actual_cost)` | 计算平台手续费 |
| `calculate_node_earn(actual_cost)` | 计算节点收入 |
| `calculate_escrow_locked(bid_price, input_tokens, output_tokens)` | 计算锁定金额 |
| `calculate_settlement(actual_cost, bid_price, actual_latency_ms)` | 计算完整结算 |

---

### RetryService (重试服务)

**位置**: `src/services/retry.py`

**核心方法**:

| 方法 | 说明 |
|------|------|
| `handle_failure(match, job, failure_type, reason)` | 处理失败 |
| `handle_node_offline(node_id, match)` | 处理节点掉线 |
| `handle_node_error(match, job, error_type)` | 处理节点错误 |
| `handle_latency_exceeded(match, job, actual_latency)` | 处理延迟超标 |
| `handle_verification_failed(match, job, reason)` | 处理验证失败 |
| `get_failure_stats()` | 获取失败统计 |

**失败类型枚举** (`FailureType`):

| 值 | 说明 |
|------|------|
| `NODE_OFFLINE` | 节点掉线 |
| `NODE_ERROR` | 节点返回错误 |
| `LATENCY_EXCEEDED` | 延迟超标 |
| `VERIFICATION_FAILED` | 验证失败 |

---

### PreLockService (Pre-Lock 服务)

**位置**: `src/services/pre_lock.py`

**核心方法**:

| 方法 | 说明 |
|------|------|
| `request_pre_lock(job_id, cluster, ttl_ms, tokens)` | 请求 Pre-Lock |
| `receive_ack(job_id, cluster)` | 接收 ACK |
| `receive_reject(job_id, cluster, reason)` | 接收 Reject |
| `check_expired(job_id, cluster)` | 检查过期 |
| `cleanup_slot_expired(cluster)` | 清理过期 |
| `get_pending_request(job_id)` | 获取待处理请求 |
| `has_pending(job_id)` | 检查是否有待处理 |
| `check_and_cleanup_expired(cluster)` | 检查并清理过期 |
| `process_expired_requests(clusters)` | 处理所有过期请求 |

**状态枚举** (`PreLockStatus`):

| 值 | 说明 |
|------|------|
| `PENDING` | 等待 Ack |
| `LOCKED` | 已确认 |
| `REJECTED` | 被拒绝 |
| `EXPIRED` | 已过期 |
| `CONVERTED` | 已转换为 Reserved |

---

### StakeService (Stake 管理)

**位置**: `src/services/stake.py`

**核心方法**:

| 方法 | 说明 |
|------|------|
| `calculate_stake_required(vram_gb)` | 计算所需 Stake |
| `deposit_stake(node_id, amount, tx_hash)` | 确认存款 |
| `get_stake_record(node_id)` | 获取记录 |
| `freeze_stake(node_id, reason, match_ids)` | 冻结 Stake |
| `submit_appeal(dispute_id, node_id, evidence, message)` | 提交申诉 |
| `get_dispute(dispute_id)` | 获取争议 |
| `get_node_disputes(node_id)` | 获取节点争议 |
| `is_node_frozen(node_id)` | 检查是否冻结 |
| `get_stats()` | 获取统计 |

**争议状态枚举** (`DisputeStatus`):

| 值 | 说明 |
|------|------|
| `PENDING` | 等待申诉 |
| `UNDER_REVIEW` | 审核中 |
| `FROZEN` | 已冻结 |
| `RESOLVED` | 已解决 |

---

### HardFilter (硬过滤)

**位置**: `src/services/hard_filter.py`

**核心方法**:

| 方法 | 说明 |
|------|------|
| `filter(cluster_or_node, job)` | 过滤单个 Cluster/Node |
| `filter_node(node, job)` | 过滤单个 Node |
| `filter_many(clusters_or_nodes, job)` | 批量过滤 |
| `filter_many_nodes(nodes, job)` | 批量过滤 Nodes |
| `get_passing_nodes(nodes, job)` | 获取通过的 Nodes |

---

### ScoringFunction (评分函数)

**位置**: `src/services/scoring.py`

**核心方法**:

| 方法 | 说明 |
|------|------|
| `calculate(cluster, job)` | 计算综合评分 |
| `get_breakdown(cluster, job)` | 获取评分明细 |
| `rank_clusters(clusters, job)` | 对 Clusters 排序 |
| `rank_slots(clusters, job)` | 对 Slots 排序 (别名) |

**评分明细** (`ScoreBreakdown`):

| 字段 | 说明 |
|------|------|
| `price_score` | 价格评分 (0-1) |
| `latency_score` | 延迟评分 (0-1) |
| `load_score` | 负载评分 (0-1) |
| `reputation_score` | 信誉评分 (0-1) |
| `compatibility_score` | 兼容性评分 (0-1) |
| `total_score` | 总分 (0-1) |

**默认权重**:
- 价格: 30%
- 延迟: 25%
- 负载: 15%
- 信誉: 15%
- 兼容性: 15%

---

## 📊 数据模型总览

### Job 模型

```python
class Job:
    job_id: str                    # Job ID
    user_id: str                   # 用户 ID
    model: Optional[str]           # 模型名称
    input_tokens: int              # 输入 tokens
    output_tokens_limit: int       # 输出 tokens 上限
    max_latency: int              # 最大延迟 (ms)
    bid_price: float              # 出价 (USDC/token)
    status: JobStatus             # 状态
    cluster_id: Optional[str]     # 匹配的 Cluster
    node_id: Optional[str]        # 匹配的 Node
    retry_count: int              # 重试次数
    messages: List[Message]       # 消息列表
```

**状态枚举** (`JobStatus`):

| 值 | 说明 |
|------|------|
| `CREATED` | 已创建 |
| `PENDING` | 等待撮合 |
| `MATCHED` | 已匹配 |
| `PRE_LOCKED` | 预锁定中 |
| `RESERVED` | 已预约 |
| `DISPATCHED` | 已分发 |
| `RUNNING` | 执行中 |
| `COMPLETED` | 执行成功 |
| `FAILED` | 执行失败 |
| `CANCELLED` | 已取消 |

---

### Node 模型

```python
class Node:
    node_id: str                   # Node ID
    user_id: str                   # 所有者
    location: Location             # 地理位置
    hardware: Hardware             # 硬件信息
    runtime: Runtime               # 运行时信息
    pricing: Pricing               # 定价
    reliability: Reliability       # 可靠性指标
    economy: Economy               # 经济模型
    state: NodeState               # 实时状态
    network: Network               # 网络/集群信息
```

**状态枚举** (`NodeStatus`):

| 值 | 说明 |
|------|------|
| `OFFLINE` | 离线 |
| `ONLINE` | 在线 |
| `BUSY` | 忙碌 |
| `LOCKED` | 锁定 |

---

### Cluster 模型

```python
class Cluster:
    cluster_id: str                # Cluster ID
    node_ids: List[str]            # 节点列表
    worker_ids: List[str]          # Worker 列表
    model: ModelInfo               # 模型信息
    capacity: CapacityInfo         # 容量信息
    pricing: PricingInfo            # 定价信息
    performance: PerformanceInfo   # 性能信息
    status: ClusterStatus          # 状态
    job_queue: List[str]           # Job 队列
    locks: List[ClusterLock]        # 当前 Locks
```

**状态枚举** (`ClusterStatus`):

| 值 | 说明 |
|------|------|
| `FREE` | 可用 |
| `PRE_LOCKED` | 预锁定中 |
| `PARTIALLY_RESERVED` | 部分预约 |
| `FULLY_RESERVED` | 完全预约 |
| `RESERVED` | 已预约 |
| `DISPATCHED` | 已分发 |
| `RUNNING` | 执行中 |
| `RELEASED` | 已释放 |
| `OVERLOADED` | 超负载 |
| `FAILED` | 失败 |

---

### Match 模型

```python
class Match:
    match_id: str                  # Match ID
    job_id: str                    # Job ID
    cluster_id: str                # Cluster ID
    node_id: str                   # Node ID
    worker_id: str                 # Worker ID
    locked_price: float            # 锁定价格
    matched_at: datetime           # 匹配时间
    model: str                    # 实际使用的模型
    result_hash: Optional[str]     # 结果哈希
    actual_latency_ms: Optional[int]  # 实际延迟
    verified: bool                 # 是否验证通过
    verification_layer: Optional[int]  # 验证层级
    layer2_consistency: Optional[float]  # Layer2 一致性
    settled: bool                  # 是否已结算
    settled_at: Optional[datetime] # 结算时间
```

---

### Escrow 模型

```python
class Escrow:
    escrow_id: str                 # Escrow ID
    job_id: str                    # Job ID
    match_id: Optional[str]        # Match ID
    locked_amount: float           # 锁定金额
    spent_amount: float           # 已花费
    refund_amount: float          # 退还金额
    status: EscrowStatus           # 状态
    actual_tokens: Optional[int]   # 实际 tokens
    actual_cost: Optional[float]   # 实际费用
    platform_fee: Optional[float]  # 平台手续费
    node_earn: Optional[float]     # 节点收入
```

**状态枚举** (`EscrowStatus`):

| 值 | 说明 |
|------|------|
| `PENDING` | 待锁定 |
| `LOCKED` | 已锁定 |
| `COMPLETED` | 已完成 |
| `SETTLED` | 已结算 |
| `REFUNDED` | 已退款 |
| `CANCELLED` | 已取消 |

---

### User 模型

```python
class User:
    user_id: str                   # 用户 ID
    auth_provider: AuthProvider   # 认证方式
    email: str                     # 邮箱
    username: Optional[str]       # 用户名
    role: UserRole                # 角色
    status: UserStatus            # 状态
    node_ids: List[str]           # 绑定的节点列表
    wallet_address: Optional[str] # 钱包地址
    reputation_score: float       # 声誉评分
    total_jobs: int              # 总 Job 数
    successful_jobs: int          # 成功 Job 数
    failed_jobs: int              # 失败 Job 数
```

---

## 🔢 枚举类型总览

### JobStatus

```python
class JobStatus(str, Enum):
    CREATED = "created"
    PENDING = "pending"
    MATCHED = "matched"
    PRE_LOCKED = "pre_locked"
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### NodeStatus

```python
class NodeStatus(str, Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    LOCKED = "locked"
```

### ClusterStatus

```python
class ClusterStatus(str, Enum):
    FREE = "free"
    PRE_LOCKED = "pre_locked"
    PARTIALLY_RESERVED = "partially_reserved"
    FULLY_RESERVED = "fully_reserved"
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    RELEASED = "released"
    OVERLOADED = "overloaded"
    FAILED = "failed"
```

### EscrowStatus

```python
class EscrowStatus(str, Enum):
    PENDING = "pending"
    LOCKED = "locked"
    COMPLETED = "completed"
    SETTLED = "settled"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"
```

### FailureType (重试)

```python
class FailureType(str, Enum):
    NODE_OFFLINE = "node_offline"
    NODE_ERROR = "node_error"
    LATENCY_EXCEEDED = "latency_exceeded"
    VERIFICATION_FAILED = "verification_failed"
```

### DisputeStatus (争议)

```python
class DisputeStatus(str, Enum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    FROZEN = "frozen"
    RESOLVED = "resolved"
```

### PreLockStatus

```python
class PreLockStatus(str, Enum):
    PENDING = "pending"
    LOCKED = "locked"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONVERTED = "converted"
```

### LockType

```python
class LockType(str, Enum):
    PRE_LOCK = "pre_lock"
    HARD_LOCK = "hard_lock"
    RUNNING = "running"
```

---

## 🔧 配置说明

### config.py

```python
# 数据库
database_url: str = "sqlite:///./dcm.db"

# API
api_host: str = "0.0.0.0"
api_port: int = 8000

# 模型限制 (MVP)
mvp_model: str = "qwen2.5:7b"
max_output_tokens: int = 256
max_latency_ms: int = 30000

# Escrow
escrow_buffer: float = 1.1

# 结算
platform_fee_rate: float = 0.05  # 5%

# 验证
layer2_sample_rate: float = 0.1  # 10% 抽样

# Node Status Store
node_status_store_backend: str = "memory"  # 或 "redis"
node_status_store_ttl_seconds: int = 30

# Stake 分级
stake_personal: float = 50.0      # < 4 GPU
stake_professional: float = 200.0 # 4-7 GPU
stake_datacenter: float = 1000.0  # >= 8 GPU
```

---

## 📚 相关文档

- [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) - 项目概览
- [README.md](./README.md) - 项目说明
- [DEVELOPMENT.md](./DEVELOPMENT.md) - 开发指南
- [TODO.md](./TODO.md) - 待办事项

---

## 🚀 快速启动

### 启动 DCM Server

```bash
cd DCM
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### 启动 Node Agent

```bash
cd DCM
python run_node_agent.py
```

---

## 🔗 快速链接

- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health
