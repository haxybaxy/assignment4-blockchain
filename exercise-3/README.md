# Exercise 3 — ERC-721 Event Tickets

The Assignment 3 ticketing app reborn as a real NFT contract. Tickets are now ERC-721 tokens; ownership and transfers come from the standard; resale uses the canonical `approve()` + `transferFrom()` marketplace pattern.

## Layout

```
exercise-3/
├── contracts/EventTickets721.sol   # ERC721 + Enumerable + URIStorage + Ownable + marketplace
├── scripts/deploy.ts               # deploy + seed two events
├── tests/EventTickets721.test.ts   # 18 tests across 7 describe blocks
├── hardhat.config.ts
├── package.json (OZ pinned to 5.0.2 — see notes)
├── tsconfig.json
├── .env.example
└── app/
    ├── app.py                       # Flask UI + dynamic metadata route
    ├── web3_client.py
    ├── requirements.txt
    ├── templates/                   # base, index (events + market), my_tickets, admin
    └── static/style.css
```

## Test cases (18 tests)

| describe                                      | it                                                                                  |
|-----------------------------------------------|-------------------------------------------------------------------------------------|
| metadata + access control                     | name = "Event Ticket", symbol = "TIX"                                               |
|                                               | supports ERC-721 / Metadata / Enumerable interfaces (`supportsInterface`)            |
|                                               | createEvent rejects empty name / 0 price / 0 supply / empty baseURI                  |
|                                               | only owner can createEvent / setEventActive / withdraw                              |
| primary sale (buyTicket)                      | mints, sequential seat numbers, correct tokenURI, both Transfer + TicketMinted     |
|                                               | overpayment is refunded                                                             |
|                                               | reverts on inactive / sold-out / underpaid / unknown event                          |
| free transfer (standard ERC-721)              | owner can transferFrom directly                                                     |
|                                               | non-owner gets `ERC721InsufficientApproval`                                         |
| resale: list / cancel                         | listForResale requires approval AND enforces 2× cap                                 |
|                                               | setApprovalForAll satisfies the approval check too                                  |
|                                               | only owner can list / cancel; AlreadyListed / NotListed paths covered               |
| resale: buyResale                             | uses transferFrom, pays seller (price − 2%), keeps fee, refunds overpay             |
|                                               | rejects buying your own / underpayment / not-listed                                 |
| listing auto-clears on out-of-band transfer   | a free transferFrom on a listed token clears the listing and emits TicketUnlisted   |
| withdraw                                      | owner-only; balance fully drained                                                   |
|                                               | empty-balance withdraw reverts with NothingToWithdraw                               |
| listedTickets view                            | enumerates exactly the tokens currently listed                                      |

```bash
cd implementation/exercise-3
npm install
npx hardhat test
```

All 18 pass.

## Design choices

### Inheritance: `ERC721 + ERC721URIStorage + ERC721Enumerable + Ownable`

- `ERC721` — the core standard. Free.
- `ERC721URIStorage` — lets each token have its own URI. Needed because seat numbers vary, so per-ticket metadata needs to differ. The alternative (just a `_baseURI()` override) requires every token in the collection to share the same prefix; we *want* per-ticket overrides for venue corrections etc.
- `ERC721Enumerable` — gives us `tokenOfOwnerByIndex(owner, i)`, which the Flask "My tickets" page uses to enumerate a wallet's holdings without scanning logs. Costs extra storage per transfer (around 60K extra gas on the first mint per address) but simplifies the client massively. Worth it for a demo.
- `Ownable` — single-admin access control, same as A3.

The four overrides at the bottom of the contract (`_update`, `_increaseBalance`, `tokenURI`, `supportsInterface`) are required by Solidity's diamond inheritance because OZ v5 funnels every state change through `_update`, and Enumerable + URIStorage both extend the same base.

### Metadata: split (on-chain canonical, off-chain pretty)

This is the explicitly graded design choice.

**On-chain** (in this contract):
- `eventId` per ticket — needed by the contract logic.
- `seatNumber` per ticket — needed for the resale cap ordering and to make tickets distinguishable beyond the tokenId.
- `originalPrice` per ticket — needed because the resale cap is `2 × originalPrice`; if we read the event's *current* `pricePerTicket` instead, an admin could lower the price after-the-fact and screw resellers.

**Off-chain** (pointed to by `tokenURI`):
- Event name (duplicated for display), date, venue, image URL, OpenSea-compatible attributes.
- For the demo we serve these from a Flask route at `/metadata/<slug>/<tokenId>.json` that reads on-chain state and combines it with a static event-level fixture. In production we'd pin the JSON to IPFS and put the IPFS URI in `baseURI` — same shape, just immutable storage.

**Why split?**
1. **Gas cost.** Storing the venue string ("Edinburgh International Conference Centre") in every ticket would cost ~100k gas per character. For 100 tickets that's prohibitive. Storage in the contract should be reserved for fields the *contract logic* depends on.
2. **Mutability.** Image URLs may change, descriptions may need typo fixes. On-chain JSON is permanent. Off-chain storage (IPFS or a CDN) lets us re-pin a fixed JSON without redeploying.
3. **Wallet UX.** Wallets and marketplaces (MetaMask, OpenSea, etalia) expect `tokenURI` to resolve to HTTP/HTTPS or IPFS, return JSON, with `name`, `description`, `image`, `attributes`. On-chain encoded JSON (data URIs) is technically valid but rendering support is inconsistent. Following the convention is cheaper than fighting it.

**What about full on-chain JSON?** It's possible (`data:application/json;base64,...`) and useful for fully autonomous NFTs — but for an event ticket where venue/image are properties of a real-world thing, off-chain is the right answer. README on Exercise 2 has an analogous "what's deliberately *not* in the contract" section.

### Resale flow

Two-step ERC-721 marketplace pattern:
1. Owner calls `approve(contract, tokenId)` — gives the marketplace permission to move that one token.
2. Owner calls `listForResale(tokenId, price)` — contract checks `getApproved(tokenId) == address(this)` (or `isApprovedForAll`), enforces the 2× cap, stores the listing.
3. Buyer calls `buyResale(tokenId) payable` — contract clears the listing, calls **the standard `transferFrom(seller, buyer, tokenId)`** (so the approval is what actually moves the NFT), pays the seller `price − 2%`, refunds overpay, keeps the fee.

The assignment specifically requires using `approve()` and `transferFrom()`. We could shortcut by calling `_transfer` internally — but explicitly going through the standard pathway demonstrates the canonical NFT-marketplace integration, and means anyone can audit the ownership change as an `Approval` followed by a `Transfer` event in the standard order.

### `_update` override clears stale listings

If a user lists a ticket and then transfers it directly via `transferFrom` (free transfer to a friend), the listing must not survive — otherwise the new owner sees a "for sale" badge they didn't put up. The `_update` override is the single funnel through which OZ v5 routes every transfer (including marketplace `buyResale`), so a one-line `listingPrice[tokenId] = 0` before delegating to `super._update` keeps marketplace state coherent regardless of how the transfer arrived.

### Security
- All admin paths gated by `Ownable`.
- Custom errors throughout — no string reasons, no silent failures.
- Resale uses CEI: clear listing → emit event → call transferFrom → pay seller → refund excess. Reentry into `buyResale` finds `listingPrice == 0` and reverts with `NotListed`.
- Listing requires explicit approval. We don't accept "I'm the owner so the contract can move my token internally" — the buyer of a non-approved token would receive a stale listing reference.
- Resale price cap (2×) prevents the contract being used as a face-value-laundering scalper market.
- 2% fee accumulates in the contract; only the owner can drain it via `withdraw` (with empty-balance revert).

### Why pin OpenZeppelin to `5.0.2` exactly
OpenZeppelin v5.4 introduced a `Bytes.sol` utility that uses the `mcopy` opcode, only available with Solidity 0.8.25+ and Cancun EVM target. A3 used Solidity 0.8.24 / Paris, and we kept the same compiler in A4 for consistency with the deploying VM contract. Pinning OZ avoids surprise breakage when minor versions ship new utilities. The other two exercises use loose `^5.0.2` because they only depend on `Ownable` / `ERC20`, neither of which transitively pulls `Bytes.sol`.

## Reflection (the three explicit questions)

### How did the *contract* change with ERC-721?

Roughly **half the contract disappeared into the standard**:

| What we wrote in A3 (custom)                                          | What ERC-721 gives us for free                          |
|-----------------------------------------------------------------------|---------------------------------------------------------|
| `Ticket` struct with `owner` field                                    | `_owners[tokenId]`                                       |
| `_tickets` mapping + `exists` flag                                    | `_ownerOf` returns `address(0)` for non-existent tokens  |
| `transferTicket(ticketId, to)` with custom validation                 | `transferFrom`, `safeTransferFrom`, `Transfer` event    |
| `ticketsOf(address)` O(n) scan                                        | `tokenOfOwnerByIndex` (via Enumerable, O(1))             |
| Custom `Transferred(ticketId, from, to)` event                        | Canonical `Transfer(from, to, tokenId)` event            |
| Manual ownership checks in every function                             | `_isAuthorized` enforced by base                         |

What we *kept* in our contract is now scoped tightly to the things ERC-721 has no opinion on: event creation/pricing/supply (primary-sale policy), the resale cap and fee (marketplace policy), and the seat/originalPrice mappings (per-ticket business state).

The contract dropped from ~350 lines (A3) to ~330 lines including the four required override boilerplate methods, but the *interesting* logic shrunk from ~250 to ~150. Everything below the line is replaceable boilerplate; everything above is the actual business.

### How did the *frontend* change?

The biggest practical change: **resale is now a two-step flow** because of how ERC-721 approvals work. In A3 the user clicked "List for resale" and the contract directly mutated state because the contract had implicit god-mode over its own struct. In A4 the user clicks "① Approve marketplace" then "② List for resale" — two transactions, each of which a wallet like MetaMask understands natively because they're standard ERC-721 calls.

Other changes:
- **Token enumeration is cheap and direct.** A3 had to scan all tickets to find ones owned by a wallet. A4 calls `balanceOf` then `tokenOfOwnerByIndex` — pagination for free.
- **Display reads `tokenURI`.** Each ticket card shows the JSON the URI resolves to (event name, image, venue, date). In A3 we made up the display layer entirely from struct fields.
- **Wallet integration becomes free.** MetaMask "View NFT" works on these tickets unmodified because they conform to the standard. A user could see their ticket directly in their wallet without our app at all.

### Are there any benefits of using NFTs for this use case?

Yes, with caveats:

**Benefits**:
- **Standard everywhere.** Any wallet, marketplace, or block explorer that knows ERC-721 reads our tickets without custom integration. OpenSea would list them, MetaMask shows them, Etherscan groups them under "ERC-721 Token Transfers" automatically.
- **Battle-tested ownership.** Approval, transfer, and operator semantics have been audited at scale — far better than rolling our own.
- **Composability.** A future contract could accept our tickets as collateral, gate access (e.g. proof-of-attendance airdrops to ticket holders), or extend with on-chain royalties (ERC-2981) without us redeploying.
- **Off-chain metadata.** Standard URI format means anyone can build a parallel display surface.

**Costs / caveats**:
- **Gas.** Each mint pays for ERC-721 + Enumerable + URIStorage state writes. A custom struct fits in two storage slots; an ERC-721 token is closer to four. For 1000 tickets the difference is real money on mainnet.
- **Standard misuse.** ERC-721 doesn't natively express "this ticket is for a specific date and is invalid after". You'd add it via metadata or a custom check. The standard is an ownership protocol, not a use-case schema.
- **Resale cap is non-standard.** Marketplaces that integrate our NFT directly (without our `buyResale`) won't enforce the cap — they just call `transferFrom` after buyer/seller agree off-chain. To make the cap binding everywhere, you'd need ERC-2981 royalties + a transfer hook that checks listing price (which adds non-standard behaviour and breaks composability). The clean answer: the cap is enforceable only inside our marketplace; outside it, transfers are free per the standard. That's an acceptable trade-off for a learning exercise; in production we'd document it loudly and reach for OpenZeppelin's `ERC721RoyaltyEnforcement` or a similar pattern.

The headline: for "verifiable, transferrable proof of admission", NFTs are the right tool. For "uniformly-priced revenue management with strict resale rules", you'd reach for an off-chain ticketing platform with on-chain receipts. We're closer to the first.

## Running locally

```bash
cd implementation/exercise-3
npm install
npx hardhat node                                    # in one terminal
npx hardhat run scripts/deploy.ts --network localhost   # in another
cd app && pip install -r requirements.txt
cp ../.env.example .env
python app.py
# browser → http://127.0.0.1:5003
```

End-to-end smoke test once running:
1. As account #1: mint a ticket from "Local Night".
2. Open `/my-tickets` — see the NFT, with metadata fetched from `tokenURI`.
3. Click "Transfer (free)" with account #2's address — confirm ownership moved.
4. Switch to account #2, "Approve marketplace", then "List for resale" at 0.06 ETH.
5. Switch to account #3, see the listing on `/`, "Buy from resale" — note seller gets 0.0588 ETH (98%) and contract holds the 0.0012 ETH fee.
6. As owner, visit `/admin` and "Withdraw all" — fee transfers to owner.
