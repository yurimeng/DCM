"""
智能合约接口
"""

from typing import Dict, Optional
from .client import Web3Client


class EscrowContract:
    """Escrow 合约接口"""
    
    def __init__(
        self,
        web3: Web3Client,
        address: str,
        abi: Optional[Dict] = None
    ):
        self.web3 = web3
        self.address = address
        self.abi = abi or self._default_abi()
    
    def _default_abi(self) -> Dict:
        """标准 ABI"""
        return {
            "create": "function create(bytes32 jobId, address node, uint256 amount)",
            "release": "function release(bytes32 jobId)",
            "refund": "function refund(bytes32 jobId)",
            "getEscrow": "function getEscrow(bytes32 jobId)",
        }
    
    async def create_escrow(self, job_id: str, node: str, amount: int) -> str:
        """创建托管"""
        # TODO: 实现合约调用
        return ""
    
    async def release(self, job_id: str) -> str:
        """释放给 Node"""
        # TODO: 实现合约调用
        return ""
    
    async def refund(self, job_id: str) -> str:
        """退款给 Buyer"""
        # TODO: 实现合约调用
        return ""


class StakeContract:
    """Stake 合约接口"""
    
    def __init__(
        self,
        web3: Web3Client,
        address: str,
        abi: Optional[Dict] = None
    ):
        self.web3 = web3
        self.address = address
        self.abi = abi or self._default_abi()
    
    def _default_abi(self) -> Dict:
        """标准 ABI"""
        return {
            "stake": "function stake()",
            "unstake": "function unstake()",
            "recordViolation": "function recordViolation(address node)",
            "slash": "function slash(address node, address recipient)",
            "getStakeInfo": "function getStakeInfo(address node)",
        }
    
    async def stake(self, amount: int) -> str:
        """质押"""
        # TODO: 实现合约调用
        return ""
    
    async def unstake(self) -> str:
        """提取质押"""
        # TODO: 实现合约调用
        return ""
    
    async def record_violation(self, node: str) -> str:
        """记录违规"""
        # TODO: 实现合约调用
        return ""
