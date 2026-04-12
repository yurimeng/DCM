const hre = require("hardhat");

async function main() {
  console.log("=== 部署 Stake 合约 ===\n");
  
  console.log("部署 Stake...");
  const Stake = await hre.ethers.getContractFactory("Stake");
  const stake = await Stake.deploy();
  await stake.waitForDeployment();
  const address = await stake.getAddress();
  
  console.log("✅ Stake deployed to:", address);
  console.log("\n请更新 .env:");
  console.log(`STAKE_CONTRACT_ADDRESS=${address}`);
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error("Error:", error.message);
    process.exit(1);
  });
