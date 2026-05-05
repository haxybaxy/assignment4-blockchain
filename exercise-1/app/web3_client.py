"""
Thin web3.py wrapper for the Vending Machine Flask UI.

Two operating modes, picked from the chainId in deployed.json:

  Local (chainId 1337) — Ganache or `hardhat node`:
      Derives 10 deterministic accounts from GANACHE_MNEMONIC so the UI can
      offer an account picker. Same convenience as A3.

  Public (any other chainId — e.g. Sepolia 11155111):
      Loads ONE account from WALLET_PRIVATE_KEY. The UI shows a single wallet,
      because on a public chain you bring your own funded key, not a faucet
      mnemonic.

This is the only file that needed to change between A3 and A4. The contract
itself, the deploy script's writes, and the Flask routes are network-agnostic.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from eth_account import Account
from web3 import Web3
from web3.middleware import geth_poa_middleware

# BIP-44 path Ganache and Hardhat use for account derivation.
_HD_PATH = "m/44'/60'/0'/0/{index}"
_NUM_LOCAL_ACCOUNTS = 10
_LOCAL_CHAIN_ID = 1337

Account.enable_unaudited_hdwallet_features()


@dataclass(frozen=True)
class LocalAccount:
    index: int
    address: str
    private_key: str


def _app_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_deployed() -> dict:
    p = _app_dir() / "deployed.json"
    if not p.exists():
        raise FileNotFoundError(
            "deployed.json not found. Run the deploy script first:\n"
            "  npx hardhat run scripts/deploy.ts --network localhost   (local)\n"
            "  npx hardhat run scripts/deploy.ts --network sepolia     (public)"
        )
    with p.open() as f:
        return json.load(f)


def _load_abi() -> list:
    p = _app_dir() / "VendingMachine.abi.json"
    if not p.exists():
        raise FileNotFoundError("VendingMachine.abi.json not found. Run the deploy script first.")
    with p.open() as f:
        return json.load(f)


def _derive_local_accounts(mnemonic: str) -> list[LocalAccount]:
    out = []
    for i in range(_NUM_LOCAL_ACCOUNTS):
        a = Account.from_mnemonic(mnemonic, account_path=_HD_PATH.format(index=i))
        out.append(LocalAccount(index=i, address=a.address, private_key=a.key.hex()))
    return out


def _single_account_from_key(private_key: str) -> list[LocalAccount]:
    a = Account.from_key(private_key)
    return [LocalAccount(index=0, address=a.address, private_key=a.key.hex())]


class VendingClient:
    def __init__(self) -> None:
        info = _load_deployed()
        abi = _load_abi()

        # Prefer the RPC the deploy script recorded; fall back to RPC_URL env.
        rpc_url = info.get("rpcUrl") or os.environ.get("RPC_URL", "http://127.0.0.1:8545")
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        # PoA middleware is harmless on Ganache and required on some public testnets.
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to RPC at {rpc_url}")

        self.address = Web3.to_checksum_address(info["address"])
        self.owner = Web3.to_checksum_address(info["owner"])
        self.chain_id = int(info["chainId"])
        self.network_name = info.get("networkName", "unknown")
        self.explorer_base = info.get("explorerBase", "")
        self.contract = self.w3.eth.contract(address=self.address, abi=abi)

        # Mode selection: local mnemonic vs single private key.
        if self.chain_id == _LOCAL_CHAIN_ID:
            mnemonic = os.environ.get("GANACHE_MNEMONIC")
            if not mnemonic:
                raise RuntimeError("GANACHE_MNEMONIC must be set for local-chain mode.")
            self.accounts = _derive_local_accounts(mnemonic)
            self.mode = "local"
        else:
            pk = os.environ.get("WALLET_PRIVATE_KEY") or os.environ.get("SEPOLIA_PRIVATE_KEY")
            if not pk:
                raise RuntimeError(
                    "WALLET_PRIVATE_KEY (or SEPOLIA_PRIVATE_KEY) must be set for public-chain mode."
                )
            self.accounts = _single_account_from_key(pk)
            self.mode = "public"

        self._by_addr = {a.address: a for a in self.accounts}

    # ----- Helpers -----

    def account_by_address(self, address: str) -> LocalAccount:
        return self._by_addr[Web3.to_checksum_address(address)]

    def eth_balance(self, address: str) -> int:
        return self.w3.eth.get_balance(Web3.to_checksum_address(address))

    def is_owner(self, address: str) -> bool:
        return Web3.to_checksum_address(address) == self.owner

    def tx_url(self, tx_hash: str) -> str:
        if not self.explorer_base:
            return ""
        h = tx_hash if tx_hash.startswith("0x") else f"0x{tx_hash}"
        return f"{self.explorer_base}/tx/{h}"

    def address_url(self, addr: str) -> str:
        if not self.explorer_base:
            return ""
        return f"{self.explorer_base}/address/{addr}"

    # ----- Reads -----

    def list_products(self) -> list[dict]:
        ids, names, prices, stocks, actives = self.contract.functions.getAllProducts().call()
        return [
            {"id": int(i), "name": n, "priceWei": int(p), "stock": int(s), "active": bool(a)}
            for i, n, p, s, a in zip(ids, names, prices, stocks, actives)
        ]

    def receipts_of(self, address: str) -> list[dict]:
        address = Web3.to_checksum_address(address)
        ids = self.contract.functions.getReceiptIdsOf(address).call()
        out = []
        for rid in ids:
            pid, buyer, qty, unit_price, ts = self.contract.functions.getReceipt(rid).call()
            out.append(
                {
                    "id": int(rid),
                    "productId": int(pid),
                    "buyer": buyer,
                    "quantity": int(qty),
                    "unitPrice": int(unit_price),
                    "timestamp": int(ts),
                }
            )
        return out

    # ----- Writes -----

    def _send(self, fn, sender: LocalAccount, value_wei: int = 0) -> dict:
        tx = fn.build_transaction(
            {
                "from": sender.address,
                "nonce": self.w3.eth.get_transaction_count(sender.address),
                "chainId": self.chain_id,
                "value": value_wei,
            }
        )
        if "gas" not in tx:
            try:
                tx["gas"] = self.w3.eth.estimate_gas(tx)
            except Exception:
                tx["gas"] = 500_000
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:
            tx["gasPrice"] = self.w3.eth.gas_price

        signed = self.w3.eth.account.sign_transaction(tx, sender.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        # Public chains take 12+ seconds per block; allow plenty of headroom.
        timeout = 60 if self.mode == "local" else 240
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        return {
            "txHash": tx_hash.hex(),
            "blockNumber": receipt.blockNumber,
            "gasUsed": receipt.gasUsed,
            "status": "success" if receipt.status == 1 else "failed",
            "txUrl": self.tx_url(tx_hash.hex()),
        }

    def purchase(self, sender_addr: str, product_id: int, quantity: int, value_wei: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.purchase(product_id, quantity), sender, value_wei)

    def add_product(self, sender_addr: str, name: str, price_wei: int, stock: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.addProduct(name, price_wei, stock), sender)

    def restock(self, sender_addr: str, product_id: int, amount: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.restockProduct(product_id, amount), sender)

    def update_price(self, sender_addr: str, product_id: int, new_price_wei: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.updatePrice(product_id, new_price_wei), sender)

    def set_active(self, sender_addr: str, product_id: int, active: bool) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.setProductActive(product_id, active), sender)

    def withdraw(self, sender_addr: str) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.withdraw(), sender)


def build_client_from_env() -> VendingClient:
    return VendingClient()
