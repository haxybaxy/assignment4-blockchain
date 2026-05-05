import { ethers } from "hardhat";
import * as fs from "fs";
import * as path from "path";

/**
 * Buy one product from the deployed VendingMachine. Reads the deployed
 * address from app/deployed.json (written by the deploy script) and uses
 * the same SEPOLIA_PRIVATE_KEY signer Hardhat is configured with.
 *
 * Usage: npx hardhat run scripts/buy.ts --network sepolia [-- <productId> <quantity>]
 * Defaults: productId=0, quantity=1.
 */
async function main() {
  const productId = Number(process.env.PRODUCT_ID ?? 0);
  const quantity = Number(process.env.QUANTITY ?? 1);

  const info = JSON.parse(
    fs.readFileSync(path.resolve(__dirname, "..", "app", "deployed.json"), "utf-8")
  );
  const [signer] = await ethers.getSigners();
  const vm = await ethers.getContractAt("VendingMachine", info.address, signer);

  const [name, priceWei, stock, active] = await vm.getProduct(productId);
  console.log(`Buying ${quantity} × ${name} (#${productId}) @ ${ethers.formatEther(priceWei)} ETH each`);
  console.log(`  stock: ${stock}, active: ${active}`);
  if (!active) throw new Error("product is paused");
  if (BigInt(quantity) > stock) throw new Error("insufficient stock");

  const total = priceWei * BigInt(quantity);
  console.log(`  paying: ${ethers.formatEther(total)} ETH`);

  const tx = await vm.purchase(productId, quantity, { value: total });
  console.log(`  tx submitted: ${tx.hash}`);
  const receipt = await tx.wait();
  console.log(`  tx mined in block ${receipt!.blockNumber}, gas used ${receipt!.gasUsed}`);
  console.log(`  Etherscan: https://sepolia.etherscan.io/tx/${tx.hash}`);

  const balance = await vm.balanceOf(signer.address, productId);
  console.log(`  your balance for product #${productId}: ${balance}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
