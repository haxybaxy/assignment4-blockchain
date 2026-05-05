import { ethers, artifacts, network } from "hardhat";
import * as fs from "fs";
import * as path from "path";

/**
 * Deploys VendingMachine to whichever network Hardhat is pointed at.
 *
 * Network-aware behaviour:
 *   - On Sepolia we seed a tiny catalogue with a 0.0001 ETH product so a
 *     reviewer can complete a purchase without burning much faucet ETH.
 *   - On any local network we seed the same 4-product catalogue used in A3
 *     so the dev experience is identical.
 *
 * Writes two files into ./app for the Flask client to read:
 *   - deployed.json (address, owner, rpc, chainId, networkName, explorerBase)
 *   - VendingMachine.abi.json (the ABI)
 */

type Seed = { name: string; priceEth: string; stock: number };

const LOCAL_SEEDS: Seed[] = [
  { name: "Soda", priceEth: "0.01", stock: 10 },
  { name: "Chips", priceEth: "0.02", stock: 5 },
  { name: "Candy Bar", priceEth: "0.005", stock: 20 },
  { name: "Water Bottle", priceEth: "0.008", stock: 15 },
];

const SEPOLIA_SEEDS: Seed[] = [
  { name: "Sticker", priceEth: "0.0001", stock: 50 },
  { name: "Pin Badge", priceEth: "0.0002", stock: 25 },
];

function networkMeta(name: string) {
  if (name === "sepolia") {
    return {
      rpcUrl: process.env.SEPOLIA_RPC_URL || "",
      explorerBase: "https://sepolia.etherscan.io",
    };
  }
  return {
    rpcUrl: "http://127.0.0.1:8545",
    explorerBase: "",
  };
}

async function main() {
  const [deployer] = await ethers.getSigners();
  const net = await ethers.provider.getNetwork();
  const chainId = Number(net.chainId);
  const networkName = network.name;

  console.log(`Deploying VendingMachine`);
  console.log(`  network: ${networkName} (chainId ${chainId})`);
  console.log(`  deployer: ${deployer.address}`);
  const balance = await ethers.provider.getBalance(deployer.address);
  console.log(`  balance: ${ethers.formatEther(balance)} ETH`);

  const Factory = await ethers.getContractFactory("VendingMachine");
  const vm = await Factory.deploy();
  await vm.waitForDeployment();
  const address = await vm.getAddress();
  console.log(`VendingMachine deployed at: ${address}`);

  const seeds = networkName === "sepolia" ? SEPOLIA_SEEDS : LOCAL_SEEDS;
  for (const s of seeds) {
    const tx = await vm.addProduct(s.name, ethers.parseEther(s.priceEth), s.stock);
    await tx.wait();
    console.log(`  + ${s.name} @ ${s.priceEth} ETH × ${s.stock}`);
  }

  const meta = networkMeta(networkName);
  const info = {
    address,
    owner: deployer.address,
    rpcUrl: meta.rpcUrl,
    chainId,
    networkName,
    explorerBase: meta.explorerBase,
    contractUrl: meta.explorerBase ? `${meta.explorerBase}/address/${address}` : "",
  };

  const artifact = await artifacts.readArtifact("VendingMachine");
  const appDir = path.resolve(__dirname, "..", "app");
  if (!fs.existsSync(appDir)) fs.mkdirSync(appDir, { recursive: true });
  fs.writeFileSync(path.join(appDir, "deployed.json"), JSON.stringify(info, null, 2));
  fs.writeFileSync(
    path.join(appDir, "VendingMachine.abi.json"),
    JSON.stringify(artifact.abi, null, 2)
  );
  console.log(`Wrote app/deployed.json and app/VendingMachine.abi.json`);

  if (info.contractUrl) {
    console.log(`\nEtherscan: ${info.contractUrl}`);
    console.log(`Verify with: npx hardhat verify --network sepolia ${address}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
