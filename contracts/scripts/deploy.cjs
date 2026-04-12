const hre = require("hardhat");

async function main() {
  console.log("=== 部署合约到 Mumbai ===\n");
  
  // 检查私钥
  if (!process.env.PRIVATE_KEY || process.env.PRIVATE_KEY === "0x0000000000000000000000000000000000000000000000000000000000000000") {
    console.log("❌ 请先填写 .env 中的 PRIVATE_KEY");
    console.log("从钱包导出私钥，然后编辑 .env 文件");
    return;
  }
  
  // 部署 Escrow
  console.log("部署 Escrow...");
  const Escrow = await hre.ethers.getContractFactory("Escrow");
  const escrow = await Escrow.deploy("0x0000000000000000000000000000000000000000");
  await escrow.waitForDeployment();
  const escrowAddress = await escrow.getAddress();
  console.log("✅ Escrow deployed to:", escrowAddress);
  
  // 部署 Stake
  console.log("\n部署 Stake...");
  const Stake = await hre.ethers.getContractFactory("Stake");
  const stake = await Stake.deploy();
  await stake.waitForDeployment();
  const stakeAddress = await stake.getAddress();
  console.log("✅ Stake deployed to:", stakeAddress);
  
  console.log("\n=== 部署完成 ===");
  console.log("\n请更新 .env:");
  console.log(`ESCROW_CONTRACT_ADDRESS=${escrowAddress}`);
  console.log(`STAKE_CONTRACT_ADDRESS=${stakeAddress}`);
  
  // 验证合约
  console.log("\n验证合约...");
  try {
    await hre.run("verify:verify", {
      address: escrowAddress,
      constructorArguments: ["0x0000000000000000000000000000000000000000"],
    });
    console.log("✅ Escrow verified");
  } catch (e) {
    console.log("⚠️ Escrow verification failed:", e.message);
  }
  
  try {
    await hre.run("verify:verify", {
      address: stakeAddress,
      constructorArguments: [],
    });
    console.log("✅ Stake verified");
  } catch (e) {
    console.log("⚠️ Stake verification failed:", e.message);
  }
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
