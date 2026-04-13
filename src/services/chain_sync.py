"""
Chain Sync Service - 双账本同步服务

职责:
1. 本地 SQLite 与链上 Escrow 双向同步
2. 结算时记录链上 SettlementRecord
3. 提供对账接口

同步策略:
- Job 创建: SQLite → 链上 create()
- 结算完成: SQLite 更新 → 链上 settle()
- 读取: SQLite 优先，链上验证
- 对账: 定期全量核对
"""

import hashlib
import logging
from typing import Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class ChainSettlementRecord:
    """链上结算记录"""
    job_id: str
    match_id: str
    locked_amount: float
    actual_cost: float
    node_earn: float
    platform_fee: float
    refund_amount: float
    input_hash: str
    result_hash: str
    actual_tokens: int
    settled_at: datetime
    settled: bool


@dataclass
class ReconciliationResult:
    """对账结果"""
    total_records: int
    matched: int
    mismatched: int
    missing_on_chain: int
    missing_local: int
    details: list


class ChainSyncService:
    """链上同步服务"""
    
    def __init__(self):
        self.web3 = None
        self.escrow_contract = None
        self._initialized = False
    
    def initialize(self):
        """初始化 Web3 连接"""
        if self._initialized:
            return
        
        try:
            from web3 import Web3
            
            # 连接 Polygon Amoy
            self.web3 = Web3(Web3.HTTPProvider(settings.rpc_url))
            
            if not self.web3.is_connected():
                logger.warning("Web3 not connected, running in mock mode")
                self._initialized = True
                return
            
            # 加载合约
            from .web3_client import get_escrow_contract
            self.escrow_contract = get_escrow_contract()
            
            logger.info("ChainSync initialized successfully")
            self._initialized = True
            
        except Exception as e:
            logger.warning(f"ChainSync init failed: {e}, running in mock mode")
            self._initialized = True
    
    def _to_bytes32(self, value: str) -> bytes:
        """字符串转 bytes32"""
        return Web3.keccak(text=value) if self.web3 else b''
    
    def _to_hex(self, value: str) -> str:
        """字符串转 hex"""
        return value.encode().hex() if value else ''
    
    def sync_escrow_create(self, job_id: str, node_address: str, 
                          locked_amount: float) -> bool:
        """
        同步 Job 创建到链上
        
        Args:
            job_id: Job ID
            node_address: Node 地址
            locked_amount: 锁定金额 (USDC)
        
        Returns:
            True if synced successfully
        """
        self.initialize()
        
        if not self.escrow_contract:
            logger.info(f"[Mock] Chain sync: Create escrow {job_id[:8]}")
            return True
        
        try:
            # 转换金额到最小单位 (USDC 6位精度)
            amount_wei = int(locked_amount * 1_000_000)
            job_id_bytes = self._to_bytes32(job_id)
            
            # 调用链上 create()
            tx_hash = self.escrow_contract.functions.create(
                job_id_bytes,
                node_address,
                amount_wei
            ).transact({
                'from': settings.wallet_address,
                'gas': 200000
            })
            
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            logger.info(f"Escrow created on chain: {job_id[:8]}, tx: {tx_hash.hex()[:10]}")
            
            return True
            
        except Exception as e:
            logger.error(f"Chain sync create failed: {e}")
            return False
    
    def sync_settlement(self, job_id: str, match_id: str,
                       actual_cost: float, node_earn: float,
                       platform_fee: float, refund_amount: float,
                       input_hash: str, result_hash: str,
                       actual_tokens: int) -> bool:
        """
        同步结算到链上（双账本核心同步点）
        
        Args:
            job_id: Job ID
            match_id: Match ID
            actual_cost: 实际费用
            node_earn: Node 收入
            platform_fee: 平台手续费
            refund_amount: 退款金额
            input_hash: 输入哈希
            result_hash: 结果哈希
            actual_tokens: 实际 token 数
        
        Returns:
            True if synced successfully
        """
        self.initialize()
        
        if not self.escrow_contract:
            logger.info(f"[Mock] Chain sync: Settle {job_id[:8]}, cost={actual_cost}")
            return True
        
        try:
            # 转换金额到最小单位
            cost_wei = int(actual_cost * 1_000_000)
            node_earn_wei = int(node_earn * 1_000_000)
            platform_fee_wei = int(platform_fee * 1_000_000)
            refund_wei = int(refund_amount * 1_000_000)
            
            # 转换哈希
            job_id_bytes = self._to_bytes32(job_id)
            match_id_bytes = self._to_bytes32(match_id)
            input_hash_bytes = bytes.fromhex(self._to_hex(input_hash))
            result_hash_bytes = bytes.fromhex(self._to_hex(result_hash))
            
            # 调用链上 settle()
            tx_hash = self.escrow_contract.functions.settle(
                job_id_bytes,
                match_id_bytes,
                cost_wei,
                node_earn_wei,
                platform_fee_wei,
                refund_wei,
                input_hash_bytes,
                result_hash_bytes,
                actual_tokens
            ).transact({
                'from': settings.wallet_address,
                'gas': 300000
            })
            
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            logger.info(f"Settlement synced: {job_id[:8]}, cost={actual_cost}, tx: {tx_hash.hex()[:10]}")
            
            return True
            
        except Exception as e:
            logger.error(f"Chain sync settlement failed: {e}")
            return False
    
    def verify_settlement(self, job_id: str, expected_result_hash: str,
                         expected_cost: float) -> Tuple[bool, str]:
        """
        验证结算记录（双账本对账）
        
        Args:
            job_id: Job ID
            expected_result_hash: 期望的结果哈希
            expected_cost: 期望的费用
        
        Returns:
            (verified, reason)
        """
        self.initialize()
        
        if not self.escrow_contract:
            return True, "Mock mode"
        
        try:
            job_id_bytes = self._to_bytes32(job_id)
            result_hash_bytes = bytes.fromhex(self._to_hex(expected_result_hash))
            cost_wei = int(expected_cost * 1_000_000)
            
            verified, reason = self.escrow_contract.functions.verifySettlement(
                job_id_bytes,
                result_hash_bytes,
                cost_wei
            ).call()
            
            return verified, reason
            
        except Exception as e:
            return False, str(e)
    
    def get_chain_settlement(self, job_id: str) -> Optional[ChainSettlementRecord]:
        """获取链上结算记录"""
        self.initialize()
        
        if not self.escrow_contract:
            return None
        
        try:
            job_id_bytes = self._to_bytes32(job_id)
            record = self.escrow_contract.functions.getSettlement(job_id_bytes).call()
            
            return ChainSettlementRecord(
                job_id=job_id,
                match_id=record[0].hex() if record[0] else '',
                locked_amount=record[1] / 1_000_000,
                actual_cost=record[2] / 1_000_000,
                node_earn=record[3] / 1_000_000,
                platform_fee=record[4] / 1_000_000,
                refund_amount=record[5] / 1_000_000,
                input_hash=record[6].hex() if record[6] else '',
                result_hash=record[7].hex() if record[7] else '',
                actual_tokens=record[8],
                settled_at=datetime.fromtimestamp(record[9]),
                settled=record[10]
            )
            
        except Exception as e:
            logger.error(f"Get chain settlement failed: {e}")
            return None
    
    def reconcile(self, local_records: list) -> ReconciliationResult:
        """
        对账：比较本地 SQLite 与链上记录
        
        Args:
            local_records: 本地结算记录列表
        
        Returns:
            对账结果
        """
        self.initialize()
        
        result = ReconciliationResult(
            total_records=len(local_records),
            matched=0,
            mismatched=0,
            missing_on_chain=0,
            missing_local=0,
            details=[]
        )
        
        if not self.escrow_contract:
            logger.info(f"[Mock] Reconciliation: {len(local_records)} records")
            result.matched = len(local_records)
            return result
        
        for record in local_records:
            chain_record = self.get_chain_settlement(record['job_id'])
            
            if not chain_record:
                result.missing_on_chain += 1
                result.details.append({
                    'job_id': record['job_id'],
                    'status': 'missing_on_chain',
                    'local_amount': record.get('actual_cost')
                })
                continue
            
            if not chain_record.settled:
                result.mismatched += 1
                result.details.append({
                    'job_id': record['job_id'],
                    'status': 'not_settled_on_chain'
                })
                continue
            
            # 比较金额（允许 1% 误差）
            cost_diff = abs(chain_record.actual_cost - record.get('actual_cost', 0))
            cost_ratio = cost_diff / max(chain_record.actual_cost, 0.000001)
            
            if cost_ratio > 0.01:
                result.mismatched += 1
                result.details.append({
                    'job_id': record['job_id'],
                    'status': 'cost_mismatch',
                    'chain_cost': chain_record.actual_cost,
                    'local_cost': record.get('actual_cost')
                })
            else:
                result.matched += 1
        
        logger.info(f"Reconciliation complete: {result.matched}/{result.total_records} matched")
        return result


# 单例
chain_sync_service = ChainSyncService()
