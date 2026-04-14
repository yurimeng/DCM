# DCM TODO - Next Steps

## 🎯 当前状态
- ✅ 核心匹配引擎工作正常
- ✅ Escrow 结算正常工作
- ✅ NodeStatusStore 集成完成
- ✅ Model 前缀匹配支持
- ✅ 压力测试通过 (10分钟, 402 jobs, 93 completed)

---

## 📋 TODO 列表

### 1. 🚀 优化用户体验 (UX)

- [ ] **简化 Job 创建流程**
  - [ ] 移除 `user_id` 必填（使用 token/auth 替代）
  - [ ] 智能默认值（自动设置合理的 bid_price, max_latency）
  - [ ] 支持更多 prompt 格式（text, messages, JSON）

- [ ] **改进错误提示**
  - [ ] 友好的错误消息（不只是 "Internal Server Error"）
  - [ ] Job 匹配失败的具体原因（为什么没匹配到节点）
  - [ ] 实时状态反馈

- [ ] **增加 API 文档和示例**
  - [ ] OpenAPI 文档完善
  - [ ] SDK/客户端库（Python, JS, Go）
  - [ ] 完整的使用示例

### 2. 🔧 Node Agent 兼容性和交互

- [ ] **多 Runtime 支持**
  - [ ] Ollama（已支持）
  - [ ] vLLM 适配器
  - [ ] TensorRT-LLM 适配器
  - [ ] Claude API 兼容层

- [ ] **Agent 交互优化**
  - [ ] 双向心跳机制
  - [ ] 自动重连
  - [ ] 离线检测和告警
  - [ ] 批量任务支持

- [ ] **标准化协议**
  - [ ] 统一 RuntimeAdapter 接口
  - [ ] 健康检查标准化
  - [ ] 性能指标上报

### 3. 🌐 前端 Web 接口封装

- [ ] **Web Dashboard**
  - [ ] 用户注册/登录
  - [ ] Job 提交表单（拖拽式）
  - [ ] 实时任务状态
  - [ ] 节点管理面板

- [ ] **API 包装**
  - [ ] RESTful 包装
  - [ ] GraphQL 接口
  - [ ] WebSocket 实时推送
  - [ ] 认证中间件

- [ ] **前端组件**
  - [ ] React/Vue 组件库
  - [ ] 在线 Playground
  - [ ] 可视化监控面板

### 4. 💼 JobCreate 增强

- [ ] **更灵活的 Job 创建**
  - [ ] 批量 Job 提交
  - [ ] Job 模板/预设
  - [ ] 定时/周期 Job
  - [ ] Job 优先级调整

- [ ] **高级选项**
  - [ ] 系统提示词（system prompt）
  - [ ] 生成参数（temperature, top_p 等）
  - [ ] Streaming 支持
  - [ ] 多模态输入（图片、音频）

- [ ] **Job 管理**
  - [ ] Job 取消/退款
  - [ ] Job 暂停/恢复
  - [ ] 历史记录和导出
  - [ ] 搜索和过滤

---

## 🏗️ 技术债务

- [ ] 添加 Redis 支持（当前用 InMemoryQueue）
- [ ] 数据库迁移脚本
- [ ] 日志规范化
- [ ] 单元测试覆盖率 > 80%
- [ ] CI/CD 流水线

---

## 📊 性能优化

- [ ] 缓存层（Redis/Memcached）
- [ ] 数据库索引优化
- [ ] 并发处理增强
- [ ] 负载均衡

---

## 🔐 安全加固

- [ ] JWT 认证
- [ ] Rate Limiting
- [ ] 输入验证增强
- [ ] 审计日志

---

## 📅 里程碑

### v3.3 - User Experience (1-2 周)
- 简化 Job 创建
- Web Dashboard MVP
- 改进错误提示

### v3.4 - Node Agent (2-3 周)
- 多 Runtime 支持
- Agent 交互优化
- 标准化协议

### v3.5 - Frontend (2-4 周)
- 完整 Web Dashboard
- SDK 发布
- Playground

### v4.0 - Production Ready (4-6 周)
- 安全加固
- 性能优化
- 监控告警

---

## 🐛 Bug 修复

- [ ] Pending Jobs 超时自动取消
- [ ] 节点离线后 Job 重分配
- [ ] Escrow 超时自动退款

---

_Last Updated: 2026-04-15_
