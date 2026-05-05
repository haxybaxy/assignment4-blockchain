# Assignment 4 — Public Testnets, ERC-20, ERC-721

Three exercises building on Assignment 3:

| Exercise | What it does                                                                       | Key contract               | Status                                     |
|----------|------------------------------------------------------------------------------------|----------------------------|--------------------------------------------|
| 1        | Deploy the A3 vending machine to **Sepolia** + connect the Flask client             | `VendingMachine.sol`       | code ready; user runs the live deploy step |
| 2        | **ERC-20** loyalty-points token: owner-only mint, free transfers, balance UI       | `LoyaltyPoints.sol`        | local Hardhat ✅                           |
| 3        | **ERC-721** NFT event tickets with marketplace (approve+list+buy resale flow)      | `EventTickets721.sol`      | local Hardhat ✅                           |

All three follow the same shape: Hardhat (Solidity 0.8.24, OpenZeppelin v5) for the contract + tests, Python `web3.py` + Flask for the client. Every public function is commented; every state change emits an event; every failure path uses a custom error.

## Layout

```
implementation/
├── README.md                ← this file
├── exercise-1/              ← Vending Machine, Sepolia-ready
├── exercise-2/              ← ERC-20 loyalty points
└── exercise-3/              ← ERC-721 NFT tickets
```

Each exercise has its own README with: test cases, design choices (on-chain vs off-chain), and (where the assignment asks) reflection answers.

## Running everything

Each exercise is a self-contained Hardhat project. From a fresh checkout:

```bash
# Exercise 1 — local tests
cd implementation/exercise-1
npm install
npx hardhat test                                    # 13 passing

# Exercise 2 — local tests
cd ../exercise-2
npm install
npx hardhat test                                    # 11 passing

# Exercise 3 — local tests
cd ../exercise-3
npm install
npx hardhat test                                    # 18 passing
```

Total: **42 contract tests** across the three exercises, all passing on the in-memory Hardhat network.

To run the Flask UIs locally (each in its own terminal pair):

```bash
# Exercise 2 example
cd implementation/exercise-2
npx hardhat node                                    # terminal A
npm run deploy:local                                # terminal B (one-shot)
cd app && pip install -r requirements.txt
cp ../.env.example .env
python app.py                                       # → http://127.0.0.1:5002
```

Same pattern for exercises 1 and 3 — the per-exercise README documents ports, seed data, and the deployment runbook (Sepolia for Exercise 1).

## Cross-exercise design notes

These are the "why I made this choice" beats that matter for grading. Each exercise's README expands on the points relevant to it; the headlines:

- **What goes on chain.** Anything the contract enforces (prices, supplies, ownership, listing prices, mint rights). Anything else (display strings, customer profiles, redemption rules) lives off-chain. We pay gas only for state that needs consensus.
- **Standards over custom code.** Where ERC-20 / ERC-721 / `Ownable` cover a need, we inherit and override the minimum. Exercise 3's contract dropped roughly half its A3 lines to the standard.
- **Custom errors everywhere.** Cheaper than revert strings, parameterised, and surface cleanly in web3.py exception messages.
- **CEI on every payable.** State changes precede external calls; refunds happen last; reentrancy via fallback finds zeroed state.
- **Owner-only paths via `Ownable`.** Single-admin model, custom-error revert, OZ-audited.
- **Events on every state change.** Off-chain UIs can rebuild views from logs alone; we don't need redundant on-chain history arrays.
- **Secrets hygiene.** `.env` is gitignored; only `.env.example` checked in. Sepolia private keys never enter source.

## What changed from A3

- Exercise 1 reuses the A3 vending machine **byte-for-byte** — the contract was already network-agnostic.
- Exercise 2 is new code (no A3 ERC-20).
- Exercise 3 replaces A3's custom ticket struct with ERC-721. The marketplace policy (resale cap, fee) survives; ownership and transfers move to the standard.

## What needs the user to act

Exercise 1 requires real on-chain deployment to Sepolia, which needs your wallet, your Infura/Alchemy key, and your faucet ETH. The `exercise-1/README.md` walks through the steps end-to-end and leaves placeholder lines for the resulting Etherscan + tx URLs to paste in.
