// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title Escrow
 * @dev USDC 托管合约 - Job 完成后释放资金
 * 
 * 流程:
 * 1. Buyer 创建 Job → 锁定 USDC 到 Escrow
 * 2. Node 完成 Job → 释放 USDC 给 Node
 * 3. 退款逻辑 (如有)
 */
contract Escrow {
    // USDC 代币地址 (测试网)
    address public usdc;
    
    // Job ID → Escrow 信息
    mapping(bytes32 => EscrowInfo) public escrows;
    
    struct EscrowInfo {
        address buyer;
        address node;
        uint256 amount;
        bool released;
        uint256 createdAt;
    }
    
    event Created(bytes32 indexed jobId, address buyer, uint256 amount);
    event Released(bytes32 indexed jobId, address node, uint256 amount);
    event Refunded(bytes32 indexed jobId, address buyer, uint256 amount);
    
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
     * @dev 释放给 Node
     */
    function release(bytes32 jobId) external {
        EscrowInfo storage escrow = escrows[jobId];
        require(!escrow.released, "Already released");
        require(msg.sender == escrow.buyer, "Only buyer");
        
        escrow.released = true;
        IERC20(usdc).transfer(escrow.node, escrow.amount);
        
        emit Released(jobId, escrow.node, escrow.amount);
    }
    
    /**
     * @dev 退款给 Buyer
     */
    function refund(bytes32 jobId) external {
        EscrowInfo storage escrow = escrows[jobId];
        require(!escrow.released, "Already released");
        require(msg.sender == escrow.buyer, "Only buyer");
        
        escrow.released = true;
        IERC20(usdc).transfer(escrow.buyer, escrow.amount);
        
        emit Refunded(jobId, escrow.buyer, escrow.amount);
    }
    
    function getEscrow(bytes32 jobId) external view returns (EscrowInfo memory) {
        return escrows[jobId];
    }
}

interface IERC20 {
    function transferFrom(address, address, uint256) external;
    function transfer(address, uint256) external;
}
