"""
web3.py wrapper for the EventTickets721 ERC-721 marketplace.

Same shape as the other exercises. The contract is the NFT *and* the
marketplace, so listing requires the user to first call `approve(contract, id)`
or `setApprovalForAll(contract, true)`. Both flows are exposed in the UI to
make the standard ERC-721 approval pattern explicit.
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
    p = _app_dir() / "EventTickets721.abi.json"
    if not p.exists():
        raise FileNotFoundError("EventTickets721.abi.json not found. Run the deploy script first.")
    with p.open() as f:
        return json.load(f)


def _derive_accounts(mnemonic: str) -> list[LocalAccount]:
    out = []
    for i in range(_NUM_ACCOUNTS):
        a = Account.from_mnemonic(mnemonic, account_path=_HD_PATH.format(index=i))
        out.append(LocalAccount(index=i, address=a.address, private_key=a.key.hex()))
    return out


class TicketClient:
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
    def list_events(self) -> list[dict]:
        ids, names, prices, supplies, solds, actives = self.contract.functions.getAllEvents().call()
        return [
            {
                "id": int(i),
                "name": n,
                "priceWei": int(p),
                "maxSupply": int(ms),
                "sold": int(s),
                "active": bool(a),
            }
            for i, n, p, ms, s, a in zip(ids, names, prices, supplies, solds, actives)
        ]

    def my_tickets(self, address: str) -> list[dict]:
        addr = Web3.to_checksum_address(address)
        n = int(self.contract.functions.balanceOf(addr).call())
        out: list[dict] = []
        for i in range(n):
            token_id = int(self.contract.functions.tokenOfOwnerByIndex(addr, i).call())
            out.append(self._ticket_summary(token_id))
        return out

    def listed_tickets(self) -> list[dict]:
        ids = self.contract.functions.listedTickets().call()
        return [self._ticket_summary(int(t)) for t in ids]

    def _ticket_summary(self, token_id: int) -> dict:
        owner = self.contract.functions.ownerOf(token_id).call()
        ev_id = int(self.contract.functions.ticketEventOf(token_id).call())
        original = int(self.contract.functions.originalPriceOf(token_id).call())
        seat = int(self.contract.functions.seatNumberOf(token_id).call())
        listing = int(self.contract.functions.listingPrice(token_id).call())
        approved = self.contract.functions.getApproved(token_id).call()
        try:
            uri = self.contract.functions.tokenURI(token_id).call()
        except Exception:
            uri = ""
        return {
            "tokenId": token_id,
            "owner": owner,
            "eventId": ev_id,
            "originalPriceWei": original,
            "seatNumber": seat,
            "listingPriceWei": listing,
            "approvedFor": approved,
            "tokenURI": uri,
            "listed": listing > 0,
            "marketplaceApproved": Web3.to_checksum_address(approved) == self.address,
        }

    def is_approved_for_all(self, owner: str, operator: str) -> bool:
        return bool(
            self.contract.functions.isApprovedForAll(
                Web3.to_checksum_address(owner), Web3.to_checksum_address(operator)
            ).call()
        )

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
                tx["gas"] = 600_000
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

    def buy_ticket(self, sender_addr: str, event_id: int, value_wei: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.buyTicket(event_id), sender, value_wei)

    def transfer(self, sender_addr: str, to: str, token_id: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(
            self.contract.functions.transferFrom(
                Web3.to_checksum_address(sender_addr), Web3.to_checksum_address(to), token_id
            ),
            sender,
        )

    def approve(self, sender_addr: str, operator: str, token_id: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(
            self.contract.functions.approve(Web3.to_checksum_address(operator), token_id),
            sender,
        )

    def list_for_resale(self, sender_addr: str, token_id: int, price_wei: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.listForResale(token_id, price_wei), sender)

    def cancel_resale(self, sender_addr: str, token_id: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.cancelResale(token_id), sender)

    def buy_resale(self, sender_addr: str, token_id: int, value_wei: int) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.buyResale(token_id), sender, value_wei)

    def create_event(
        self, sender_addr: str, name: str, price_wei: int, max_supply: int, base_uri: str
    ) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(
            self.contract.functions.createEvent(name, price_wei, max_supply, base_uri),
            sender,
        )

    def withdraw(self, sender_addr: str) -> dict:
        sender = self.account_by_address(sender_addr)
        return self._send(self.contract.functions.withdraw(), sender)


def build_client_from_env() -> TicketClient:
    rpc = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
    mnemonic = os.environ.get("GANACHE_MNEMONIC")
    if not mnemonic:
        raise RuntimeError("GANACHE_MNEMONIC not set; copy .env.example to .env")
    return TicketClient(rpc_url=rpc, mnemonic=mnemonic)
