"""
链上 Escrow 服务
替换 MockWalletService 中的 Escrow 逻辑
"""

from typing import Optional
from config import settings
from .escrow import escrow_service


class ChainEscrowService:
    """
    链上 Escrow 服务
    
    当 USE_BLOCKCHAIN=true 时使用真实链上合约
    否则使用 Mock 模式
    """
    
    def __init__(self):
        self._web3_client = None
        self._contract = None
    
    def _get_contract(self):
        """获取合约实例"""
        if not settings.USE_BLOCKCHAIN:
            return None
        
        if not self._contract:
            from src.web3 import Web3Client, EscrowContract
            self._web3_client = Web3Client()
            self._web3_client.connect()
            self._contract = EscrowContract(
                self._web3_client,
                settings.ESCROW_CONTRACT_ADDRESS
            )
        return self._contract
    
    async def lock(self, job_id: str, buyer: str, node: str, amount: int) -> str:
        """
        锁定 USDC
        
        Returns: 交易哈希
        """
        contract = self._get_contract()
        
        if contract:
            return await contract.create_escrow(job_id, node, amount)
        else:
            # Mock 模式
            return escrow_service.lock(job_id, buyer, node, amount)
    
    async def release(self, job_id: str) -> str:
        """
        释放给 Node
        
        Returns: 交易哈希
        """
        contract = self._get_contract()
        
        if contract:
            return await contract.release(job_id)
        else:
            # Mock 模式
            return escrow_service.release(job_id)
    
    async def refund(self, job_id: str) -> str:
        """
        退款给 Buyer
        
        Returns: 交易哈希
        """
        contract = self._get_contract()
        
        if contract:
            return await contract.refund(job_id)
        else:
            # Mock 模式
            return escrow_service.refund(job_id)


# 单例
chain_escrow_service = ChainEscrowService()
