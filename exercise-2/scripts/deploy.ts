import { ethers, artifacts, network } from "hardhat";
import * as fs from "fs";
import * as path from "path";

/**
 * Deploys LoyaltyPoints, mints a couple of starter rewards to the next two
 * accounts (so the Flask UI has something to show on first load), and writes
 * deployment metadata + ABI to ./app for the client.
 */
async function main() {
  const signers = await ethers.getSigners();
  const deployer = signers[0];
  const net = await ethers.provider.getNetwork();
  const chainId = Number(net.chainId);

  console.log(`Deploying LoyaltyPoints on ${network.name} (chainId ${chainId})`);
  console.log(`  deployer: ${deployer.address}`);

  const Factory = await ethers.getContractFactory("LoyaltyPoints");
  const token = await Factory.deploy();
  await token.waitForDeployment();
  const address = await token.getAddress();
  console.log(`LoyaltyPoints deployed at: ${address}`);

  // Seed: give two demo customers some points so the UI isn't empty on a fresh deploy.
  if (signers.length >= 3) {
    const seedRecipients = [signers[1].address, signers[2].address];
    const seedAmounts = [100n, 50n];
    for (let i = 0; i < seedRecipients.length; i++) {
      const tx = await token.mint(seedRecipients[i], seedAmounts[i]);
      await tx.wait();
      console.log(`  + minted ${seedAmounts[i]} LOYAL → ${seedRecipients[i]}`);
    }
  }

  const info = {
    address,
    owner: deployer.address,
    rpcUrl: "http://127.0.0.1:8545",
    chainId,
    networkName: network.name,
    explorerBase: "",
    contractUrl: "",
  };

  const artifact = await artifacts.readArtifact("LoyaltyPoints");
  const appDir = path.resolve(__dirname, "..", "app");
  if (!fs.existsSync(appDir)) fs.mkdirSync(appDir, { recursive: true });
  fs.writeFileSync(path.join(appDir, "deployed.json"), JSON.stringify(info, null, 2));
  fs.writeFileSync(path.join(appDir, "LoyaltyPoints.abi.json"), JSON.stringify(artifact.abi, null, 2));
  console.log("Wrote app/deployed.json and app/LoyaltyPoints.abi.json");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
