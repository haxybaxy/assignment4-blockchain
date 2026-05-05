import { expect } from "chai";
import { ethers } from "hardhat";
import { LoyaltyPoints } from "../typechain-types";

async function deploy(): Promise<LoyaltyPoints> {
  const Factory = await ethers.getContractFactory("LoyaltyPoints");
  const c = await Factory.deploy();
  await c.waitForDeployment();
  return c as unknown as LoyaltyPoints;
}

describe("LoyaltyPoints", () => {
  describe("metadata", () => {
    it("has name, symbol, 0 decimals, and zero initial supply", async () => {
      const c = await deploy();
      expect(await c.name()).to.equal("Loyalty Points");
      expect(await c.symbol()).to.equal("LOYAL");
      expect(await c.decimals()).to.equal(0);
      expect(await c.totalSupply()).to.equal(0n);
    });

    it("sets the deployer as owner", async () => {
      const [deployer] = await ethers.getSigners();
      const c = await deploy();
      expect(await c.owner()).to.equal(deployer.address);
    });
  });

  describe("mint (owner only)", () => {
    it("owner can mint, balance + total supply update, two events emitted", async () => {
      const [owner, alice] = await ethers.getSigners();
      const c = await deploy();
      // ERC20 emits Transfer(0x0, alice, 100); we also emit LoyaltyMinted.
      await expect(c.mint(alice.address, 100))
        .to.emit(c, "Transfer")
        .withArgs(ethers.ZeroAddress, alice.address, 100n)
        .and.to.emit(c, "LoyaltyMinted")
        .withArgs(alice.address, 100n);

      expect(await c.balanceOf(alice.address)).to.equal(100n);
      expect(await c.totalSupply()).to.equal(100n);
      // owner intentionally has zero — they issue, they don't hoard.
      expect(await c.balanceOf(owner.address)).to.equal(0n);
    });

    it("reverts when a non-owner tries to mint", async () => {
      const [, alice, bob] = await ethers.getSigners();
      const c = await deploy();
      await expect(c.connect(alice).mint(bob.address, 50)).to.be.revertedWithCustomError(
        c,
        "OwnableUnauthorizedAccount"
      );
    });

    it("reverts on zero amount", async () => {
      const [, alice] = await ethers.getSigners();
      const c = await deploy();
      await expect(c.mint(alice.address, 0)).to.be.revertedWithCustomError(c, "ZeroAmount");
    });

    it("reverts on mint to the zero address (OZ check)", async () => {
      const c = await deploy();
      await expect(c.mint(ethers.ZeroAddress, 1)).to.be.revertedWithCustomError(
        c,
        "ERC20InvalidReceiver"
      );
    });
  });

  describe("transfer", () => {
    it("user can transfer their points to another user", async () => {
      const [, alice, bob] = await ethers.getSigners();
      const c = await deploy();
      await c.mint(alice.address, 100);
      await expect(c.connect(alice).transfer(bob.address, 30))
        .to.emit(c, "Transfer")
        .withArgs(alice.address, bob.address, 30n);

      expect(await c.balanceOf(alice.address)).to.equal(70n);
      expect(await c.balanceOf(bob.address)).to.equal(30n);
    });

    it("transfer of more than balance reverts with ERC20InsufficientBalance", async () => {
      const [, alice, bob] = await ethers.getSigners();
      const c = await deploy();
      await c.mint(alice.address, 10);
      await expect(c.connect(alice).transfer(bob.address, 100)).to.be.revertedWithCustomError(
        c,
        "ERC20InsufficientBalance"
      );
    });

    it("transfer to zero reverts with ERC20InvalidReceiver", async () => {
      const [, alice] = await ethers.getSigners();
      const c = await deploy();
      await c.mint(alice.address, 10);
      await expect(c.connect(alice).transfer(ethers.ZeroAddress, 1)).to.be.revertedWithCustomError(
        c,
        "ERC20InvalidReceiver"
      );
    });
  });

  describe("approve + transferFrom", () => {
    it("allowance flow works end-to-end", async () => {
      const [, alice, bob, carol] = await ethers.getSigners();
      const c = await deploy();
      await c.mint(alice.address, 100);

      await expect(c.connect(alice).approve(bob.address, 40))
        .to.emit(c, "Approval")
        .withArgs(alice.address, bob.address, 40n);
      expect(await c.allowance(alice.address, bob.address)).to.equal(40n);

      // bob sends 25 of alice's points to carol on her behalf
      await c.connect(bob).transferFrom(alice.address, carol.address, 25);
      expect(await c.balanceOf(alice.address)).to.equal(75n);
      expect(await c.balanceOf(carol.address)).to.equal(25n);
      expect(await c.allowance(alice.address, bob.address)).to.equal(15n);
    });

    it("transferFrom over allowance reverts with ERC20InsufficientAllowance", async () => {
      const [, alice, bob, carol] = await ethers.getSigners();
      const c = await deploy();
      await c.mint(alice.address, 100);
      await c.connect(alice).approve(bob.address, 10);
      await expect(
        c.connect(bob).transferFrom(alice.address, carol.address, 50)
      ).to.be.revertedWithCustomError(c, "ERC20InsufficientAllowance");
    });
  });
});
