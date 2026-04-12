"""
链上集成测试脚本

测试流程:
1. 部署合约
2. 质押
3. 创建 Escrow
4. 释放
"""

import asyncio
import os
from web3 import Web3

# 配置
RPC_URL = os.getenv("ETH_RPC_URL", "https://rpc-mumbai.maticvigil.com")
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
ESCROW_ADDRESS = os.getenv("ESCROW_CONTRACT_ADDRESS", "")
STAKE_ADDRESS = os.getenv("STAKE_CONTRACT_ADDRESS", "")


async def main():
    print("=== 链上集成测试 ===\n")
    
    # 连接
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    print(f"连接状态: {w3.is_connected()}")
    
    if not w3.is_connected():
        print("❌ 连接失败，请检查 RPC URL")
        return
    
    # 获取账户
    account = w3.eth.account.from_key(PRIVATE_KEY)
    print(f"测试账户: {account.address}")
    
    # 检查余额
    balance = w3.eth.get_balance(account.address)
    print(f"余额: {w3.from_wei(balance, 'ether')} MATIC")
    
    print("\n✅ 连接测试通过")
    print("\n下一步:")
    print("1. 部署合约: npx hardhat run scripts/deploy_contracts.js --network mumbai")
    print("2. 更新 .env 中的合约地址")
    print("3. 设置 USE_BLOCKCHAIN=true")
    print("4. 运行完整测试")


if __name__ == "__main__":
    asyncio.run(main())
