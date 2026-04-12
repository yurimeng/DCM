// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title Stake
 * @dev 节点质押合约
 * 
 * 规则:
 * - 节点需质押最低金额才能参与
 * - 连续 3 次违规 → 质押被罚没
 * - 正常退出 → 质押可提取
 */
contract Stake {
    // 最低质押金额
    uint256 public constant MIN_STAKE = 200 * 1e6; // 200 USDC
    
    // 节点质押信息
    mapping(address => StakeInfo) public stakes;
    
    struct StakeInfo {
        uint256 amount;
        uint256 violations;
        uint256 lastViolationTime;
        bool locked;
    }
    
    event Staked(address indexed node, uint256 amount);
    event Unstaked(address indexed node, uint256 amount);
    event Slashed(address indexed node, uint256 amount, string reason);
    
    /**
     * @dev 质押
     */
    function stake() external payable {
        require(msg.value >= MIN_STAKE, "Below minimum");
        
        stakes[msg.sender].amount += msg.value;
        
        emit Staked(msg.sender, msg.value);
    }
    
    /**
     * @dev 提取质押（需解锁）
     */
    function unstake() external {
        require(!stakes[msg.sender].locked, "Stake locked");
        require(stakes[msg.sender].violations < 3, "Too many violations");
        
        uint256 amount = stakes[msg.sender].amount;
        require(amount > 0, "No stake");
        
        stakes[msg.sender].amount = 0;
        payable(msg.sender).transfer(amount);
        
        emit Unstaked(msg.sender, amount);
    }
    
    /**
     * @dev 记录违规（由验证服务调用）
     */
    function recordViolation(address node) external {
        stakes[node].violations++;
        stakes[node].lastViolationTime = block.timestamp;
        
        if (stakes[node].violations >= 3) {
            stakes[node].locked = true;
        }
    }
    
    /**
     * @dev 罚没（转移给系统）
     */
    function slash(address node, address recipient) external {
        require(stakes[node].locked, "Not locked");
        
        uint256 amount = stakes[node].amount;
        stakes[node].amount = 0;
        
        // 转给指定地址（可以是国库地址）
        payable(recipient).transfer(amount);
        
        emit Slashed(node, amount, "Max violations");
    }
    
    function getStakeInfo(address node) external view returns (StakeInfo memory) {
        return stakes[node];
    }
}
