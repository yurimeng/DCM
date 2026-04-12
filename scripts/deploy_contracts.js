/**
 * 部署合约脚本
 * 
 * 使用 Hardhat:
 * npx hardhat run scripts/deploy_contracts.js --network mumbai
 */

const hre = require("hardhat");

async function main() {
  console.log("部署合约到 Polygon Mumbai...");
  
  // 部署 Escrow
  const Escrow = await hre.ethers.getContractFactory("Escrow");
  const escrow = await Escrow.deploy(process.env.USDC_ADDRESS);
  await escrow.deployed();
  console.log("Escrow deployed to:", escrow.address);
  
  // 部署 Stake
  const Stake = await hre.ethers.getContractFactory("Stake");
  const stake = await Stake.deploy();
  await stake.deployed();
  console.log("Stake deployed to:", stake.address);
  
  console.log("\n部署完成!");
  console.log("请更新 .env 文件:");
  console.log(`ESCROW_CONTRACT_ADDRESS=${escrow.address}`);
  console.log(`STAKE_CONTRACT_ADDRESS=${stake.address}`);
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
