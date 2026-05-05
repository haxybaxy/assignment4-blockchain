# Exercise 1 — Vending Machine on Sepolia

Take the Assignment 3 vending machine **as-is** and put it on a public testnet.

## Layout

```
exercise-1/
├── contracts/VendingMachine.sol     # unchanged from A3
├── scripts/deploy.ts                # network-aware (local seeds vs Sepolia seeds)
├── tests/VendingMachine.test.ts     # unchanged from A3 (10 tests)
├── hardhat.config.ts                # adds sepolia network + etherscan plugin
├── package.json                     # adds @nomicfoundation/hardhat-verify, dotenv
├── .env.example                     # all required env vars documented
└── app/
    ├── app.py                       # Flask UI
    ├── web3_client.py               # NEW: switches between mnemonic mode and single-key mode
    ├── requirements.txt
    ├── templates/                   # adds network badge + clickable etherscan links
    └── static/
```

## Test cases

`tests/VendingMachine.test.ts` covers (10 tests, all ported from A3):

| Test                                              | What it pins down                                  |
|---------------------------------------------------|----------------------------------------------------|
| owner adds product, emits `ProductAdded`          | admin happy path + event arg shape                 |
| reject empty name / zero price                    | input validation via custom errors                 |
| purchase decrements stock, records receipt        | core happy path + ownership tracking               |
| refunds excess ETH                                | CEI + payable refund correctness                   |
| ownership accumulates over multiple buys          | aggregation invariant                              |
| `InsufficientPayment` revert                      | underpaid call rejected                            |
| `InsufficientStock` revert                        | overdraft prevented                                |
| `ProductInactive` revert                          | paused product rejects buyers                      |
| `ProductNotFound` revert                          | unknown id rejected                                |
| non-owner restock / addProduct / updatePrice fail | access control                                     |
| restock + price update events fire correctly      | state-mutation events                              |
| owner-only `withdraw` empties contract balance    | money-flow correctness                             |

Run them locally:

```bash
cd implementation/exercise-1
npm install
npx hardhat test
```

These tests run on the in-memory Hardhat network — fast, deterministic, **don't** burn faucet ETH. Only the deploy step touches Sepolia.

## Design choices

### What is on-chain
- **Product catalogue** (`name`, `priceWei`, `stock`, `active`) — these drive payment validation and must therefore be authoritative. Putting them on-chain is what stops the contract from being a centralised database with extra steps.
- **Receipts and aggregated ownership balances** — the assignment requires verifiable on-chain ownership of bought items. Keeping a per-user receipt list is cheap (push-only) and gives the UI a deterministic history that doesn't depend on a log indexer.

### What is off-chain
- **Pretty product images, descriptions, marketing copy** — none of it is here. The contract stores only what it needs to *enforce*. Display is the UI's job.
- **Account derivation in dev mode** — the Flask UI derives 10 deterministic accounts from a mnemonic only when `chainId == 1337`. On Sepolia we use a real wallet key the user controls.

### Security posture
- All admin functions gated by OZ `Ownable` with custom-error reverts.
- Payments use Checks-Effects-Interactions: state changes (stock, receipt, balance) precede the refund `call`, so reentrancy cannot drain a half-decremented product.
- `transfer` to owner uses low-level `call` with explicit success check (Solidity 0.8 + custom error) rather than `.transfer()`'s 2300-gas stipend, which can break against contracts that need more gas for fallback logic.

## Reflection — what changed moving from Ganache to Sepolia?

**Smart-contract side: literally nothing.** The Solidity is byte-for-byte the same as A3. A well-scoped contract that uses standard primitives (`Ownable`, custom errors, `payable`) is network-agnostic — Sepolia executes the same EVM as your local node.

**Front-end side: three real changes.**

1. **Account model.** Locally we derive 10 wallets from a deterministic mnemonic so the UI has a "switch account" picker for free. On Sepolia that mnemonic is unfunded — we have to use a single private key the user funded from the faucet. `web3_client.py` branches on `chainId` and exposes either a list of 10 dev accounts or a single real account. The base template disables the picker accordingly.
2. **Latency and feedback.** Ganache mines instantly; Sepolia mines roughly every 12 seconds. `_send()` raises `wait_for_transaction_receipt` timeout from 60s to 240s in public mode, and the UI now shows the transaction-hash link to Etherscan so the user has somewhere to monitor while they wait.
3. **Gas is real, faucet ETH is finite.** The deploy script seeds a smaller, cheaper catalogue when `network.name === "sepolia"` (just `Sticker @ 0.0001 ETH` and `Pin Badge @ 0.0002 ETH`) so a reviewer can actually complete a purchase without exhausting faucet allowance.

Things that *didn't* need to change but matter:
- ABI loading and `_send()` build-sign-broadcast logic are identical.
- Custom errors decode the same way (web3.py 6 surfaces them in the exception string).
- Owner-gated paths still work because `msg.sender` semantics are universal.

## Deployment runbook

1. **Generate a Sepolia wallet.** Easiest: install MetaMask, select Sepolia network, create a fresh account, export the private key (Account details → Show private key). Or in Python: `from eth_account import Account; print(Account.create().key.hex())`.

2. **Fund it from the faucet.** Visit <https://cloud.google.com/application/web3/faucet>, paste the wallet address, request 0.05 SepoliaETH. Wait one block.

3. **Get a Sepolia RPC URL.** Sign up for Alchemy or Infura free tier, create an app on Sepolia, copy the HTTPS URL.

4. **(Optional) Get an Etherscan API key** from <https://etherscan.io/myapikey> for source verification.

5. **Configure env.**
   ```bash
   cd implementation/exercise-1
   cp .env.example .env
   # edit .env: SEPOLIA_RPC_URL, SEPOLIA_PRIVATE_KEY, ETHERSCAN_API_KEY, WALLET_PRIVATE_KEY
   ```

6. **Compile + test locally.**
   ```bash
   npm install
   npx hardhat compile
   npx hardhat test
   ```

7. **Deploy to Sepolia.**
   ```bash
   npx hardhat run scripts/deploy.ts --network sepolia
   # → prints contract address + Etherscan URL
   # → writes app/deployed.json + app/VendingMachine.abi.json
   ```

8. **Verify source on Etherscan** (so the reviewer can read it without your repo):
   ```bash
   npx hardhat verify --network sepolia <CONTRACT_ADDRESS>
   ```

9. **Run the front-end and buy a product.**
   ```bash
   cd app
   pip install -r requirements.txt
   python app.py
   # browser → http://127.0.0.1:5001 → buy Sticker → flash message contains tx URL
   ```

10. **Paste your URLs below** as proof of homework:

```
Sepolia contract:  https://sepolia.etherscan.io/address/<TODO>
Verify (optional): https://sepolia.etherscan.io/address/<TODO>#code
Purchase tx 1:     https://sepolia.etherscan.io/tx/<TODO>
Purchase tx 2:     https://sepolia.etherscan.io/tx/<TODO>
```
