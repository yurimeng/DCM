"""
Web3 客户端
"""

import os
from typing import Optional


class Web3Client:
    """Web3 客户端"""
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        private_key: Optional[str] = None,
        chain_id: int = None
    ):
        from config import ETH_RPC_URL, PRIVATE_KEY, CHAIN_ID
        
        self.rpc_url = rpc_url or ETH_RPC_URL
        self.private_key = private_key or PRIVATE_KEY
        self.chain_id = chain_id or CHAIN_ID
        self._provider = None
        self._wallet = None
        self._connected = False
    
    def connect(self) -> bool:
        """连接区块链"""
        try:
            from web3 import Web3
            self._provider = Web3(Web3.HTTPProvider(self.rpc_url))
            self._connected = self._provider.is_connected()
            
            if self._connected and self.private_key:
                self._wallet = self._provider.eth.account.from_key(self.private_key)
            
            return self._connected
        except ImportError:
            print("请安装 web3: pip install web3")
            return False
        except Exception as e:
            print(f"连接失败: {e}")
            return False
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self._connected
    
    @property
    def address(self) -> str:
        """获取钱包地址"""
        return self._wallet.address if self._wallet else ""
    
    def get_balance(self, address: str = None) -> int:
        """获取余额 (wei)"""
        if not self._connected:
            return 0
        addr = address or self.address
        return self._provider.eth.get_balance(addr)


# 单例
web3_client = Web3Client()
