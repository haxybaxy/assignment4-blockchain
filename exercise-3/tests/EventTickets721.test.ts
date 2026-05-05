import { expect } from "chai";
import { ethers } from "hardhat";
import { EventTickets721 } from "../typechain-types";

const PRICE = ethers.parseEther("0.05");
const BASE_URI = "https://demo.test/metadata/";

async function deploy(): Promise<EventTickets721> {
  const Factory = await ethers.getContractFactory("EventTickets721");
  const c = await Factory.deploy();
  await c.waitForDeployment();
  return c as unknown as EventTickets721;
}

async function deployWithEvent(maxSupply = 100n) {
  const c = await deploy();
  await c.createEvent("Concert", PRICE, maxSupply, BASE_URI);
  return c;
}

describe("EventTickets721", () => {
  describe("metadata + access control", () => {
    it("has correct name and symbol", async () => {
      const c = await deploy();
      expect(await c.name()).to.equal("Event Ticket");
      expect(await c.symbol()).to.equal("TIX");
    });

    it("supports ERC-721, ERC-721 Metadata, ERC-721 Enumerable interfaces", async () => {
      const c = await deploy();
      const ERC721 = "0x80ac58cd";
      const ERC721_METADATA = "0x5b5e139f";
      const ERC721_ENUMERABLE = "0x780e9d63";
      expect(await c.supportsInterface(ERC721)).to.equal(true);
      expect(await c.supportsInterface(ERC721_METADATA)).to.equal(true);
      expect(await c.supportsInterface(ERC721_ENUMERABLE)).to.equal(true);
    });

    it("createEvent rejects empty name / zero price / zero supply / empty baseURI", async () => {
      const c = await deploy();
      await expect(c.createEvent("", PRICE, 10, BASE_URI)).to.be.revertedWithCustomError(c, "EmptyName");
      await expect(c.createEvent("X", 0, 10, BASE_URI)).to.be.revertedWithCustomError(c, "ZeroPrice");
      await expect(c.createEvent("X", PRICE, 0, BASE_URI)).to.be.revertedWithCustomError(c, "ZeroSupply");
      await expect(c.createEvent("X", PRICE, 10, "")).to.be.revertedWithCustomError(c, "EmptyBaseURI");
    });

    it("only owner can createEvent / setEventActive / withdraw", async () => {
      const c = await deployWithEvent();
      const [, alice] = await ethers.getSigners();
      await expect(
        c.connect(alice).createEvent("Hack", PRICE, 1, BASE_URI)
      ).to.be.revertedWithCustomError(c, "OwnableUnauthorizedAccount");
      await expect(c.connect(alice).setEventActive(0, false)).to.be.revertedWithCustomError(
        c,
        "OwnableUnauthorizedAccount"
      );
      await expect(c.connect(alice).withdraw()).to.be.revertedWithCustomError(
        c,
        "OwnableUnauthorizedAccount"
      );
    });
  });

  describe("primary sale (buyTicket)", () => {
    it("mints an NFT to the buyer with sequential seat numbers and correct tokenURI", async () => {
      const c = await deployWithEvent();
      const [, alice, bob] = await ethers.getSigners();

      await expect(c.connect(alice).buyTicket(0, { value: PRICE }))
        .to.emit(c, "Transfer") // standard ERC-721 mint event
        .withArgs(ethers.ZeroAddress, alice.address, 0n)
        .and.to.emit(c, "TicketMinted")
        .withArgs(0n, 0n, alice.address, 1n, PRICE);

      await c.connect(bob).buyTicket(0, { value: PRICE });

      expect(await c.ownerOf(0)).to.equal(alice.address);
      expect(await c.ownerOf(1)).to.equal(bob.address);
      expect(await c.balanceOf(alice.address)).to.equal(1n);
      expect(await c.seatNumberOf(0)).to.equal(1n);
      expect(await c.seatNumberOf(1)).to.equal(2n);
      expect(await c.originalPriceOf(0)).to.equal(PRICE);
      expect(await c.tokenURI(0)).to.equal(`${BASE_URI}0.json`);
      expect(await c.tokenURI(1)).to.equal(`${BASE_URI}1.json`);
    });

    it("refunds overpayment", async () => {
      const c = await deployWithEvent();
      const [, alice] = await ethers.getSigners();
      const overpay = ethers.parseEther("0.01");
      const balBefore = await ethers.provider.getBalance(alice.address);
      const tx = await c.connect(alice).buyTicket(0, { value: PRICE + overpay });
      const receipt = await tx.wait();
      const gas = receipt!.fee;
      const balAfter = await ethers.provider.getBalance(alice.address);
      // Net spent = PRICE + gas, NOT PRICE + overpay + gas
      expect(balBefore - balAfter).to.equal(PRICE + gas);
      expect(await ethers.provider.getBalance(await c.getAddress())).to.equal(PRICE);
    });

    it("reverts on inactive event / sold out / underpayment / unknown event", async () => {
      const c = await deployWithEvent(2n);
      const [, alice] = await ethers.getSigners();

      await expect(
        c.connect(alice).buyTicket(0, { value: PRICE / 2n })
      ).to.be.revertedWithCustomError(c, "IncorrectPayment");

      await expect(
        c.connect(alice).buyTicket(99, { value: PRICE })
      ).to.be.revertedWithCustomError(c, "EventNotFound");

      await c.setEventActive(0, false);
      await expect(
        c.connect(alice).buyTicket(0, { value: PRICE })
      ).to.be.revertedWithCustomError(c, "EventInactive");
      await c.setEventActive(0, true);

      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await expect(
        c.connect(alice).buyTicket(0, { value: PRICE })
      ).to.be.revertedWithCustomError(c, "SoldOut");
    });
  });

  describe("free transfer (standard ERC-721)", () => {
    it("owner can transferFrom directly", async () => {
      const c = await deployWithEvent();
      const [, alice, bob] = await ethers.getSigners();
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).transferFrom(alice.address, bob.address, 0);
      expect(await c.ownerOf(0)).to.equal(bob.address);
    });

    it("non-owner cannot transferFrom (OZ guard)", async () => {
      const c = await deployWithEvent();
      const [, alice, bob, carol] = await ethers.getSigners();
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await expect(
        c.connect(bob).transferFrom(alice.address, carol.address, 0)
      ).to.be.revertedWithCustomError(c, "ERC721InsufficientApproval");
    });
  });

  describe("resale: list / cancel", () => {
    it("listForResale requires approval and enforces 2× cap", async () => {
      const c = await deployWithEvent();
      const [, alice] = await ethers.getSigners();
      const contractAddr = await c.getAddress();
      await c.connect(alice).buyTicket(0, { value: PRICE });

      // Without approval: revert.
      await expect(
        c.connect(alice).listForResale(0, PRICE)
      ).to.be.revertedWithCustomError(c, "NotApproved");

      // Approve and try a price above the cap.
      await c.connect(alice).approve(contractAddr, 0);
      const cap = PRICE * 2n;
      await expect(
        c.connect(alice).listForResale(0, cap + 1n)
      ).to.be.revertedWithCustomError(c, "PriceTooHigh");

      // At-cap is fine and emits TicketListed.
      await expect(c.connect(alice).listForResale(0, cap))
        .to.emit(c, "TicketListed")
        .withArgs(0n, alice.address, cap);
      expect(await c.listingPrice(0)).to.equal(cap);
    });

    it("setApprovalForAll satisfies the approval check too", async () => {
      const c = await deployWithEvent();
      const [, alice] = await ethers.getSigners();
      const contractAddr = await c.getAddress();
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).setApprovalForAll(contractAddr, true);
      await c.connect(alice).listForResale(0, PRICE); // ok
    });

    it("only owner can list / cancel; relisting requires no listing first", async () => {
      const c = await deployWithEvent();
      const [, alice, bob] = await ethers.getSigners();
      const contractAddr = await c.getAddress();
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).approve(contractAddr, 0);

      // Bob can't list a ticket he doesn't own.
      await expect(
        c.connect(bob).listForResale(0, PRICE)
      ).to.be.revertedWithCustomError(c, "NotTicketOwner");

      await c.connect(alice).listForResale(0, PRICE);
      // Already listed.
      await expect(
        c.connect(alice).listForResale(0, PRICE)
      ).to.be.revertedWithCustomError(c, "AlreadyListed");

      // Bob can't cancel either.
      await expect(c.connect(bob).cancelResale(0)).to.be.revertedWithCustomError(
        c,
        "NotTicketOwner"
      );

      await expect(c.connect(alice).cancelResale(0))
        .to.emit(c, "TicketUnlisted")
        .withArgs(0n, alice.address);

      // Cancel again → not listed.
      await expect(c.connect(alice).cancelResale(0)).to.be.revertedWithCustomError(
        c,
        "NotListed"
      );
    });
  });

  describe("resale: buyResale", () => {
    it("transfers via transferFrom, pays seller (price − 2%), keeps fee in contract, refunds overpay", async () => {
      const c = await deployWithEvent();
      const [, alice, bob] = await ethers.getSigners();
      const contractAddr = await c.getAddress();
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).approve(contractAddr, 0);
      const listPrice = PRICE * 2n;
      await c.connect(alice).listForResale(0, listPrice);

      const aliceBalBefore = await ethers.provider.getBalance(alice.address);
      const overpay = ethers.parseEther("0.001");

      const expectedFee = (listPrice * 200n) / 10_000n; // 2%
      const expectedProceeds = listPrice - expectedFee;

      await expect(c.connect(bob).buyResale(0, { value: listPrice + overpay }))
        .to.emit(c, "TicketResold")
        .withArgs(0n, alice.address, bob.address, listPrice, expectedProceeds, expectedFee)
        .and.to.emit(c, "Transfer") // standard ERC-721 transfer event
        .withArgs(alice.address, bob.address, 0n);

      // Buyer is the new owner
      expect(await c.ownerOf(0)).to.equal(bob.address);
      // Listing cleared
      expect(await c.listingPrice(0)).to.equal(0n);

      // Seller received proceeds
      const aliceBalAfter = await ethers.provider.getBalance(alice.address);
      expect(aliceBalAfter - aliceBalBefore).to.equal(expectedProceeds);

      // Contract holds exactly the protocol fee
      // (it also held PRICE from the primary sale already, so total = PRICE + fee)
      expect(await ethers.provider.getBalance(contractAddr)).to.equal(PRICE + expectedFee);
    });

    it("rejects buying your own ticket and rejects underpayment / not-listed", async () => {
      const c = await deployWithEvent();
      const [, alice, bob] = await ethers.getSigners();
      const contractAddr = await c.getAddress();
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).approve(contractAddr, 0);
      await c.connect(alice).listForResale(0, PRICE);

      await expect(
        c.connect(alice).buyResale(0, { value: PRICE })
      ).to.be.revertedWithCustomError(c, "CannotBuyOwnTicket");

      await expect(
        c.connect(bob).buyResale(0, { value: PRICE - 1n })
      ).to.be.revertedWithCustomError(c, "IncorrectPayment");

      // After cancel, NotListed.
      await c.connect(alice).cancelResale(0);
      await expect(
        c.connect(bob).buyResale(0, { value: PRICE })
      ).to.be.revertedWithCustomError(c, "NotListed");
    });
  });

  describe("listing auto-clears on out-of-band transfer", () => {
    it("transferFrom (free) clears any active listing and emits TicketUnlisted", async () => {
      const c = await deployWithEvent();
      const [, alice, bob] = await ethers.getSigners();
      const contractAddr = await c.getAddress();
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).approve(contractAddr, 0);
      await c.connect(alice).listForResale(0, PRICE);
      expect(await c.listingPrice(0)).to.equal(PRICE);

      // Alice approves bob personally (so bob can't accidentally re-trigger
      // the marketplace path) and bob does a plain transferFrom — actually,
      // alice does it herself for clarity.
      await expect(c.connect(alice).transferFrom(alice.address, bob.address, 0))
        .to.emit(c, "TicketUnlisted")
        .withArgs(0n, alice.address);

      expect(await c.listingPrice(0)).to.equal(0n);
      expect(await c.ownerOf(0)).to.equal(bob.address);
    });
  });

  describe("withdraw", () => {
    it("owner can withdraw protocol fees, non-owner cannot", async () => {
      const c = await deployWithEvent();
      const [owner, alice, bob] = await ethers.getSigners();
      const contractAddr = await c.getAddress();

      // Generate a fee: alice mints, lists at 2× cap, bob buys.
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).approve(contractAddr, 0);
      const listPrice = PRICE * 2n;
      await c.connect(alice).listForResale(0, listPrice);
      await c.connect(bob).buyResale(0, { value: listPrice });

      const balBefore = await ethers.provider.getBalance(owner.address);
      const tx = await c.withdraw();
      const r = await tx.wait();
      const gas = r!.fee;
      const balAfter = await ethers.provider.getBalance(owner.address);
      const expectedTotal = PRICE + (listPrice * 200n) / 10_000n;
      expect(balAfter - balBefore + gas).to.equal(expectedTotal);
      expect(await ethers.provider.getBalance(contractAddr)).to.equal(0n);
    });

    it("withdraw with empty balance reverts", async () => {
      const c = await deploy();
      await expect(c.withdraw()).to.be.revertedWithCustomError(c, "NothingToWithdraw");
    });
  });

  describe("listedTickets view", () => {
    it("enumerates exactly the currently-listed tokens", async () => {
      const c = await deployWithEvent();
      const [, alice] = await ethers.getSigners();
      const contractAddr = await c.getAddress();
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).buyTicket(0, { value: PRICE });
      await c.connect(alice).setApprovalForAll(contractAddr, true);
      await c.connect(alice).listForResale(0, PRICE);
      await c.connect(alice).listForResale(2, PRICE);

      const listed = (await c.listedTickets()).map((b: bigint) => Number(b));
      expect(listed.sort()).to.deep.equal([0, 2]);
    });
  });
});
