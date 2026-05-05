import { ethers, artifacts, network } from "hardhat";
import * as fs from "fs";
import * as path from "path";

/**
 * Deploys EventTickets721 and seeds two demo events whose tokenURI base
 * points to the Flask app's static metadata folder. Writes deployment info +
 * ABI to ./app for the Flask client to read.
 */

type EventSeed = { name: string; priceEth: string; maxSupply: number; baseURI: string };

const APP_HOST = "http://127.0.0.1:5003";
// baseURI points at a Flask route that resolves <tokenId>.json from on-chain
// state — same shape we'd use with IPFS in production, but dynamic for the demo.
const SEEDS: EventSeed[] = [
  {
    name: "Local Night",
    priceEth: "0.05",
    maxSupply: 100,
    baseURI: `${APP_HOST}/metadata/local-night/`,
  },
  {
    name: "Tech Conf 2026",
    priceEth: "0.08",
    maxSupply: 50,
    baseURI: `${APP_HOST}/metadata/tech-conf-2026/`,
  },
];

async function main() {
  const [deployer] = await ethers.getSigners();
  const net = await ethers.provider.getNetwork();
  const chainId = Number(net.chainId);
  console.log(`Deploying EventTickets721 on ${network.name} (chainId ${chainId})`);
  console.log(`  deployer: ${deployer.address}`);

  const Factory = await ethers.getContractFactory("EventTickets721");
  const c = await Factory.deploy();
  await c.waitForDeployment();
  const address = await c.getAddress();
  console.log(`EventTickets721 deployed at: ${address}`);

  for (const e of SEEDS) {
    const tx = await c.createEvent(
      e.name,
      ethers.parseEther(e.priceEth),
      e.maxSupply,
      e.baseURI
    );
    await tx.wait();
    console.log(`  + Event "${e.name}" @ ${e.priceEth} ETH × ${e.maxSupply}`);
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

  const artifact = await artifacts.readArtifact("EventTickets721");
  const appDir = path.resolve(__dirname, "..", "app");
  if (!fs.existsSync(appDir)) fs.mkdirSync(appDir, { recursive: true });
  fs.writeFileSync(path.join(appDir, "deployed.json"), JSON.stringify(info, null, 2));
  fs.writeFileSync(
    path.join(appDir, "EventTickets721.abi.json"),
    JSON.stringify(artifact.abi, null, 2)
  );
  console.log("Wrote app/deployed.json and app/EventTickets721.abi.json");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
