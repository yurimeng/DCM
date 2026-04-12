"""
链上 Stake 服务
"""

from typing import Optional
from config import settings


class ChainStakeService:
    """
    链上 Stake 服务
    
    当 USE_BLOCKCHAIN=true 时使用真实链上合约
    """
    
    def __init__(self):
        self._web3_client = None
        self._contract = None
    
    def _get_contract(self):
        """获取合约实例"""
        if not settings.USE_BLOCKCHAIN:
            return None
        
        if not self._contract:
            from src.web3 import Web3Client, StakeContract
            self._web3_client = Web3Client()
            self._web3_client.connect()
            self._contract = StakeContract(
                self._web3_client,
                settings.STAKE_CONTRACT_ADDRESS
            )
        return self._contract
    
    async def stake(self, node: str, amount: int) -> str:
        """节点质押"""
        contract = self._get_contract()
        
        if contract:
            return await contract.stake(amount)
        else:
            # Mock 模式使用现有服务
            from .stake import stake_service
            return stake_service.stake(node, amount)
    
    async def unstake(self, node: str) -> str:
        """节点提取质押"""
        contract = self._get_contract()
        
        if contract:
            return await contract.unstake()
        else:
            from .stake import stake_service
            return stake_service.unstake(node)
    
    async def record_violation(self, node: str) -> str:
        """记录违规"""
        contract = self._get_contract()
        
        if contract:
            return await contract.record_violation(node)
        else:
            from .stake import stake_service
            return stake_service.record_violation(node)
    
    async def slash(self, node: str) -> str:
        """罚没"""
        contract = self._get_contract()
        
        if contract:
            return await contract.slash(node, settings.SYSTEM_ADDRESS)
        else:
            from .stake import stake_service
            return stake_service.slash(node)


# 单例
chain_stake_service = ChainStakeService()
