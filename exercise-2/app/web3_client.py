"""
web3.py wrapper for the LoyaltyPoints ERC-20.

Mirrors the structure of exercise-1/app/web3_client.py: 10 deterministic local
accounts derived from a Ganache mnemonic for dev convenience. Contract reads
go through plain `.call()`; writes build/sign/broadcast and wait for a receipt.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from eth_account import Account
from web3 import Web3
from web3.middleware import geth_poa_middleware

_HD_PATH = "m/44'/60'/0'/0/{index}"
_NUM_ACCOUNTS = 10

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
            "deployed.json not found. Run:\n  npx hardhat run scripts/deploy.ts --network localhost"
        )
    with p.open() as f:
        return json.load(f)


def _load_abi() -> list:
    p = _app_dir() / "LoyaltyPoints.abi.json"
    if not p.exists():
        raise FileNotFoundError("LoyaltyPoints.abi.json not found. Run the deploy script first.")
    with p.open() as f:
        return json.load(f)


def _derive_accounts(mnemonic: str) -> list[LocalAccount]:
    out = []
    for i in range(_NUM_ACCOUNTS):
        a = Account.from_mnemonic(mnemonic, account_path=_HD_PATH.format(index=i))
        out.append(LocalAccount(index=i, address=a.address, private_key=a.key.hex()))
    return out


class LoyaltyClient:
    def __init__(self, rpc_url: str, mnemonic: str) -> None:
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to RPC at {rpc_url}")

        info = _load_deployed()
        abi = _load_abi()
        self.address = Web3.to_checksum_address(info["address"])
        self.owner = Web3.to_checksum_address(info["owner"])
        self.chain_id = int(info["chainId"])
        self.contract = self.w3.eth.contract(address=self.address, abi=abi)
        self.accounts = _derive_accounts(mnemonic)
        self._by_addr = {a.address: a for a in self.accounts}

    # ----- Helpers -----
    def account_by_address(self, address: str) -> LocalAccount:
        return self._by_addr[Web3.to_checksum_address(address)]

    def is_owner(self, address: str) -> bool:
        return Web3.to_checksum_address(address) == self.owner

    def eth_balance(self, address: str) -> int:
        return self.w3.eth.get_balance(Web3.to_checksum_address(address))

    # ----- Reads -----
    def name(self) -> str:
        return self.contract.functions.name().call()

    def symbol(self) -> str:
        return self.contract.functions.symbol().call()

    def decimals(self) -> int:
        return int(self.contract.functions.decimals().call())

    def total_supply(self) -> int:
        return int(self.contract.functions.totalSupply().call())

    def balance_of(self, address: str) -> int:
        return int(self.contract.functions.balanceOf(Web3.to_checksum_address(address)).call())

    def recent_transfers(self, address: str, limit: int = 25) -> list[dict]:
        """Scan recent Transfer logs touching `address` (sender or receiver)."""
        addr = Web3.to_checksum_address(address)
        latest = self.w3.eth.block_number
        # 5,000-block window is plenty for a dev chain — keep the scan cheap.
        from_block = max(0, latest - 5000)
        ev = self.contract.events.Transfer
        logs_in = ev.create_filter(fromBlock=from_block, argument_filters={"to": addr}).get_all_entries()
        logs_out = ev.create_filter(fromBlock=from_block, argument_filters={"from": addr}).get_all_entries()
        rows: list[dict] = []
        for log in list(logs_in) + list(logs_out):
            rows.append(
                {
                    "blockNumber": int(log.blockNumber),
                    "txHash": log.transactionHash.hex(),
                    "from": log.args["from"],
                    "to": log.args["to"],
                    "value": int(log.args["value"]),
                }
            )
        rows.sort(key=lambda r: r["blockNumber"], reverse=True)
        return rows[:limit]

    # ----- Writes -----
    def _send(self, fn, sender: LocalAccount) -> dict:
        tx = fn.build_transaction(
            {
                "from": sender.address,
                "nonce": self.w3.eth.get_transaction_count(sender.address),
                "chainId": self.chain_id,
            }
        )
        if "gas" not in tx:
            try:
                tx["gas"] = self.w3.eth.estimate_gas(tx)
            except Exception:
                tx["gas"] = 300_000
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:
            tx["gasPrice"] = self.w3.eth.gas_price
        signed = self.w3.eth.account.sign_transaction(tx, sender.private_key)
        h = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(h, timeout=60)
        return {
            "txHash": h.hex(),
            "blockNumber": receipt.blockNumber,
            "gasUsed": receipt.gasUsed,
            "status": "success" if receipt.status == 1 else "failed",
        }

    def transfer(self, sender_addr: str, to: str, amount: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.transfer(Web3.to_checksum_address(to), amount), sender)

    def mint(self, sender_addr: str, to: str, amount: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.mint(Web3.to_checksum_address(to), amount), sender)


def build_client_from_env() -> LoyaltyClient:
    rpc = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
    mnemonic = os.environ.get("GANACHE_MNEMONIC")
    if not mnemonic:
        raise RuntimeError("GANACHE_MNEMONIC not set; copy .env.example to .env")
    return LoyaltyClient(rpc_url=rpc, mnemonic=mnemonic)
