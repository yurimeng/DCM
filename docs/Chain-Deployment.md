# 链上部署指南

## Sprint 5: 链上集成

### 前置要求

1. **Node.js** (v16+)
2. **Hardhat** 
   ```bash
   npm install -D hardhat @nomicfoundation/hardhat-toolbox
   ```
3. **测试网 MATIC** (Mumbai Faucet)
   - https://mumbaifaucet.com/
4. **测试网 USDC** (可选)

### 部署步骤

#### 1. 安装依赖

```bash
cd contracts
npm install
```

#### 2. 配置环境变量

```bash
cp ../.env.example .env
# 编辑 .env 填写私钥和 RPC
```

#### 3. 部署到 Mumbai 测试网

```bash
npx hardhat run scripts/deploy_contracts.js --network mumbai
```

输出示例:
```
Escrow deployed to: 0x1234...
Stake deployed to: 0x5678...
```

#### 4. 更新配置

```bash
# .env
ESCROW_CONTRACT_ADDRESS=0x1234...
STAKE_CONTRACT_ADDRESS=0x5678...
USE_BLOCKCHAIN=true
```

#### 5. 测试

```bash
python scripts/test_chain.py
```

### 合约验证

```bash
npx hardhat verify --network mumbai <CONTRACT_ADDRESS> <CONSTRUCTOR_ARGS>
```

### 主网部署

1. 确保有足够的 MATIC
2. 更换 RPC 为 https://rpc.polygon.technology
3. 更新 CHAIN_ID=137

### 安全检查

- [ ] 私钥不提交到 GitHub
- [ ] 使用硬件钱包或冷钱包
- [ ] 验证合约源码
- [ ] 测试网充分测试

## 合约地址

| 网络 | Escrow | Stake |
|------|--------|-------|
| Mumbai | - | - |
| Polygon | - | - |
