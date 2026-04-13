// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title Escrow
 * @dev USDC 托管合约 - Job 完成后释放资金
 * 
 * 双账本模式:
 * 1. 本地 SQLite: 快速读写，日常业务
 * 2. 链上记录: 不可篡改，争议仲裁
 * 
 * 流程:
 * 1. Buyer 创建 Job → 锁定 USDC 到 Escrow（链上 + SQLite）
 * 2. Node 完成 Job → 记录结算哈希（链上）
 * 3. 结算 → 释放 USDC 给 Node（链上 + SQLite）
 */
contract Escrow {
    // USDC 代币地址 (Polygon Amoy)
    address public usdc;
    
    // Job ID → Escrow 信息
    mapping(bytes32 => EscrowInfo) public escrows;
    
    // Job ID → 结算记录（用于对账）
    mapping(bytes32 => SettlementRecord) public settlements;
    
    struct EscrowInfo {
        address buyer;
        address node;
        uint256 amount;
        bool released;
        uint256 createdAt;
    }
    
    struct SettlementRecord {
        bytes32 matchId;
        uint256 lockedAmount;
        uint256 actualCost;
        uint256 nodeEarn;
        uint256 platformFee;
        uint256 refundAmount;
        bytes32 inputHash;
        bytes32 resultHash;
        uint256 actualTokens;
        uint256 settledAt;
        bool settled;
    }
    
    event Created(bytes32 indexed jobId, address buyer, uint256 amount);
    event Settled(
        bytes32 indexed jobId,
        bytes32 matchId,
        uint256 actualCost,
        uint256 nodeEarn,
        uint256 refundAmount
    );
    event Released(bytes32 indexed jobId, address node, uint256 amount);
    event Refunded(bytes32 indexed jobId, address buyer, uint256 amount);
    event Reconciled(bytes32 indexed jobId, bytes32 expectedHash);
    
    constructor(address _usdc) {
        usdc = _usdc;
    }
    
    /**
     * @dev 创建托管
     * @param jobId Job ID
     * @param node Node 地址
     * @param amount 锁定金额
     */
    function create(bytes32 jobId, address node, uint256 amount) external {
        require(escrows[jobId].createdAt == 0, "Escrow exists");
        
        escrows[jobId] = EscrowInfo({
            buyer: msg.sender,
            node: node,
            amount: amount,
            released: false,
            createdAt: block.timestamp
        });
        
        // 从 Buyer 转入 USDC
        IERC20(usdc).transferFrom(msg.sender, address(this), amount);
        
        emit Created(jobId, msg.sender, amount);
    }
    
    /**
     * @dev 记录结算（双账本同步点）
     * @param jobId Job ID
     * @param matchId Match ID
     * @param actualCost 实际费用
     * @param nodeEarn Node 收入
     * @param platformFee 平台手续费
     * @param refundAmount 退款金额
     * @param inputHash 输入哈希
     * @param resultHash 结果哈希
     * @param actualTokens 实际 token 数
     */
    function settle(
        bytes32 jobId,
        bytes32 matchId,
        uint256 actualCost,
        uint256 nodeEarn,
        uint256 platformFee,
        uint256 refundAmount,
        bytes32 inputHash,
        bytes32 resultHash,
        uint256 actualTokens
    ) external {
        require(escrows[jobId].createdAt > 0, "Escrow not found");
        require(!settlements[jobId].settled, "Already settled");
        
        settlements[jobId] = SettlementRecord({
            matchId: matchId,
            lockedAmount: escrows[jobId].amount,
            actualCost: actualCost,
            nodeEarn: nodeEarn,
            platformFee: platformFee,
            refundAmount: refundAmount,
            inputHash: inputHash,
            resultHash: resultHash,
            actualTokens: actualTokens,
            settledAt: block.timestamp,
            settled: true
        });
        
        emit Settled(jobId, matchId, actualCost, nodeEarn, refundAmount);
    }
    
    /**
     * @dev 获取结算记录（用于对账）
     */
    function getSettlement(bytes32 jobId) external view returns (SettlementRecord memory) {
        return settlements[jobId];
    }
    
    /**
     * @dev 验证结算记录（双账本对账）
     */
    function verifySettlement(
        bytes32 jobId,
        bytes32 expectedResultHash,
        uint256 expectedCost
    ) external view returns (bool verified, string memory reason) {
        SettlementRecord memory record = settlements[jobId];
        
        if (!record.settled) {
            return (false, "Not settled on chain");
        }
        
        if (record.resultHash != expectedResultHash) {
            return (false, "Result hash mismatch");
        }
        
        if (record.actualCost != expectedCost) {
            return (false, "Cost mismatch");
        }
        
        return (true, "Verified");
    }
    
    /**
     * @dev 释放给 Node
     */
    function release(bytes32 jobId) external {
        EscrowInfo storage escrow = escrows[jobId];
        require(!escrow.released, "Already released");
        require(msg.sender == escrow.buyer, "Only buyer");
        
        // 从结算记录获取金额
        uint256 nodeAmount = settlements[jobId].settled 
            ? settlements[jobId].nodeEarn 
            : escrow.amount;
        
        escrow.released = true;
        IERC20(usdc).transfer(escrow.node, nodeAmount);
        
        emit Released(jobId, escrow.node, nodeAmount);
    }
    
    /**
     * @dev 退款给 Buyer
     */
    function refund(bytes32 jobId) external {
        EscrowInfo storage escrow = escrows[jobId];
        require(!escrow.released, "Already released");
        require(msg.sender == escrow.buyer, "Only buyer");
        
        escrow.released = true;
        
        uint256 refundAmount = settlements[jobId].settled
            ? settlements[jobId].refundAmount
            : escrow.amount;
        
        IERC20(usdc).transfer(escrow.buyer, refundAmount);
        
        emit Refunded(jobId, escrow.buyer, refundAmount);
    }
    
    /**
     * @dev 获取 Escrow 状态
     */
    function getEscrow(bytes32 jobId) external view returns (EscrowInfo memory) {
        return escrows[jobId];
    }
}

/**
 * @dev IERC20 接口
 */
interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}
