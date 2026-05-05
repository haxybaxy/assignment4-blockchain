# Exercise 2 — ERC-20 Loyalty Points

A bare-bones ERC-20 token where the deploying business is the only minter, and customers can hand points around freely with the standard `transfer`/`approve` flow.

## Layout

```
exercise-2/
├── contracts/LoyaltyPoints.sol     # ERC20 + Ownable + decimals=0 + LoyaltyMinted event
├── scripts/deploy.ts               # deploy + seed two demo customers
├── tests/LoyaltyPoints.test.ts     # 11 tests covering metadata, mint, transfer, approve flow
├── hardhat.config.ts
├── package.json, tsconfig.json
├── .env.example
└── app/
    ├── app.py                       # Flask UI (balance / transfer / admin mint)
    ├── web3_client.py               # mirrors exercise-1's structure
    ├── requirements.txt
    ├── templates/                   # base, index (balance + transfer), admin (mint)
    └── static/style.css
```

## Test cases

11 tests across four describe blocks:

| Describe / it                                                           | Pins down                                            |
|-------------------------------------------------------------------------|------------------------------------------------------|
| metadata: name, symbol, decimals=0, totalSupply=0                       | constructor + decimals override                      |
| metadata: deployer is owner                                             | OZ Ownable wired correctly                           |
| mint: owner can mint, balances + supply update, two events fire         | happy path + dual-event design                       |
| mint: non-owner reverts with `OwnableUnauthorizedAccount`               | access control                                       |
| mint: zero amount reverts with `ZeroAmount`                             | custom validation                                    |
| mint: zero address reverts with `ERC20InvalidReceiver`                  | OZ guard surfaces correctly                          |
| transfer: user transfers, balances update, `Transfer` event             | core ERC-20 path                                     |
| transfer: over-balance reverts with `ERC20InsufficientBalance`          | OZ guard                                             |
| transfer: to zero reverts with `ERC20InvalidReceiver`                   | OZ guard                                             |
| approve + transferFrom: full allowance flow including allowance decay   | delegated transfers work                             |
| transferFrom: over-allowance reverts with `ERC20InsufficientAllowance`  | OZ guard                                             |

```bash
cd implementation/exercise-2
npm install
npx hardhat test
```

## Design choices

### What is on-chain
- **Balances** (the entire point of an ERC-20).
- **Total supply** (free in the OZ implementation, lets clients show issuance).
- **Ownership of the mint right** (single privileged address via OZ `Ownable`).
- **Allowances** (the delegated-spending model in ERC-20).
- **Two events on mint**: the canonical `Transfer(0x0, to, amount)` (so any indexer / wallet recognises the issuance) **plus** a custom `LoyaltyMinted(to, amount)` so loyalty-specific listeners don't have to filter Transfer logs by `from == 0x0`.

### What is off-chain
- **Customer profiles, identities, contact details.** None of the contract logic needs them, and putting them on-chain would be a privacy and gas catastrophe.
- **Reasons for minting** ("birthday bonus", "first-purchase reward"). We keep the on-chain event minimal — `(to, amount)`. Reason strings live in the business's CRM. They're audit data, not consensus data.
- **Redemption catalogue** (what 50 points actually buys). Business policy, mutable, off-chain.
- **Display/branding** (logo URI, marketing copy). The token has a name + symbol because ERC-20 specifies them; everything else is the wallet/UI's job.

### What's deliberately *not* in the contract
- **Burnable.** Customers might want to redeem points for a coffee. We could inherit `ERC20Burnable`, but in a proper loyalty system the *business* would burn the points after off-chain fulfilment, so it's better modelled as `transfer(business, amount)` in the MVP. README flag — easy to add later.
- **Pausable.** Reasonable for a regulated business, but adds a privileged "freeze everyone's balance" power. Out of scope here.
- **Capped supply.** Loyalty programs typically have unbounded issuance — the business mints when customers earn. A cap doesn't reflect the use case.
- **Per-mint whitelist / role separation** (e.g. an `OperatorRole` distinct from owner). Useful at scale; YAGNI for the MVP.

Documenting *why* we didn't add things matters as much as the things we did — the assignment explicitly grades design choices.

### Decimals = 0
Loyalty points are unit-counted. "You have 50.7 points" is meaningless for a coffee-shop scheme; `decimals = 0` keeps the on-chain value identical to the human-facing value, no `parseUnits/formatUnits` round-tripping. If we ever needed fractional accruals (e.g. earn-rate tied to dollars spent), we'd switch to `decimals = 2` and migrate.

### Why two events on mint
ERC-20's `Transfer(0x0, to, amount)` is the canonical "tokens came into existence" signal — every wallet, indexer, and explorer reads it. We *also* emit `LoyaltyMinted(to, amount)` because:
- Loyalty-specific listeners (the business's CRM webhook) want a stream of *issuance* events without false positives from regular transfers; filtering Transfer logs on `from == 0x0` works but is awkward.
- It's a tiny gas cost in exchange for clearer downstream consumers.

### Security
- `mint` gated by `onlyOwner`. Custom `ZeroAmount` revert prevents accidental no-ops that would emit empty events.
- `transfer`/`approve`/`transferFrom` come from OZ — battle-tested implementation, named errors (`ERC20InsufficientBalance`, `ERC20InvalidReceiver`, etc.).
- No `payable` paths and no external calls means there's no reentrancy surface to defend.

## Running locally

```bash
cd implementation/exercise-2
npm install
npx hardhat node                                    # in one terminal
npx hardhat run scripts/deploy.ts --network localhost   # in another
cd app && pip install -r requirements.txt
cp ../.env.example .env                             # default mnemonic is fine for hardhat node
python app.py
# browser → http://127.0.0.1:5002
```

The deploy script seeds 100 LOYAL to account #1 and 50 LOYAL to account #2, so you can immediately switch wallets and test transfers.
