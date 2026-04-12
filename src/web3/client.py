"""
Web3 客户端
封装 ethers.js 交互
"""

import os
from typing import Optional
from config import settings


class Web3Client:
    """
    Web3 客户端
    
    配置:
    - ETH_RPC_URL: 节点 RPC URL
    - PRIVATE_KEY: 钱包私钥
    - CHAIN_ID: 链 ID
    """
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        private_key: Optional[str] = None,
        chain_id: int = 80001  # Polygon Mumbai 测试网
    ):
        self.rpc_url = rpc_url or os.getenv("ETH_RPC_URL", "https://rpc-mumbai.maticvigil.com")
        self.private_key = private_key or os.getenv("PRIVATE_KEY", "")
        self.chain_id = chain_id
        
        # TODO: 集成 ethers.py 或 web3.py
        self._provider = None
        self._wallet = None
    
    def connect(self) -> bool:
        """连接区块链"""
        # TODO: 实现连接
        # from web3 import Web3
        # self._provider = Web3(Web3.HTTPProvider(self.rpc_url))
        return True
    
    def get_balance(self, address: str) -> int:
        """获取余额 (wei)"""
        # TODO: 实现
        return 0
    
    def send_transaction(self, to: str, value: int, data: str = "") -> str:
        """发送交易"""
        # TODO: 实现
        return ""
    
    @property
    def address(self) -> str:
        """获取钱包地址"""
        return self._wallet.address if self._wallet else ""
