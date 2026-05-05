"""
Flask UI for the LoyaltyPoints ERC-20.

Routes:
  /             show your balance, recent transfer history, and a transfer form
  /switch       change active account
  /transfer     POST: transfer points to another address
  /admin        owner-only: mint new points to an arbitrary address
  /admin/mint   POST: do the mint
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for

from web3_client import build_client_from_env

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")

client = build_client_from_env()


def _selected_account() -> str:
    addr = session.get("account")
    if addr and any(a.address == addr for a in client.accounts):
        return addr
    return client.accounts[0].address


def _account_options() -> list[dict]:
    return [
        {
            "index": a.index,
            "address": a.address,
            "balanceLoyal": client.balance_of(a.address),
            "balanceEth": client.eth_balance(a.address) / 10**18,
            "isOwner": client.is_owner(a.address),
        }
        for a in client.accounts
    ]


@app.context_processor
def _common():
    selected = _selected_account()
    return {
        "selected_account": selected,
        "is_owner": client.is_owner(selected),
        "account_options": _account_options(),
        "contract_address": client.address,
        "owner_address": client.owner,
        "token_name": client.name(),
        "token_symbol": client.symbol(),
        "token_decimals": client.decimals(),
        "total_supply": client.total_supply(),
    }


@app.post("/switch-account")
def switch_account():
    addr = request.form.get("account", "").strip()
    if addr and any(a.address == addr for a in client.accounts):
        session["account"] = addr
        flash(f"Switched to {addr[:10]}…", "info")
    return redirect(request.referrer or url_for("index"))


@app.get("/")
def index():
    addr = _selected_account()
    balance = client.balance_of(addr)
    transfers = client.recent_transfers(addr)
    return render_template("index.html", balance=balance, transfers=transfers, my_address=addr)


@app.post("/transfer")
def transfer():
    sender = _selected_account()
    to = request.form.get("to", "").strip()
    try:
        amount = int(request.form.get("amount", "0"))
    except ValueError:
        flash("Amount must be a whole number.", "error")
        return redirect(url_for("index"))
    if amount <= 0:
        flash("Amount must be > 0.", "error")
        return redirect(url_for("index"))
    if not to:
        flash("Recipient address required.", "error")
        return redirect(url_for("index"))
    try:
        r = client.transfer(sender, to, amount)
        flash(
            f"Sent {amount} {client.symbol()} to {to[:10]}… — tx {r['txHash'][:12]}… "
            f"(block {r['blockNumber']}, gas {r['gasUsed']})",
            "success",
        )
    except Exception as e:
        flash(f"Transfer failed: {_reason(e)}", "error")
    return redirect(url_for("index"))


@app.get("/admin")
def admin_panel():
    if not client.is_owner(_selected_account()):
        flash("Admin panel is only for the contract owner.", "error")
        return redirect(url_for("index"))
    return render_template("admin.html")


@app.post("/admin/mint")
def admin_mint():
    if not client.is_owner(_selected_account()):
        flash("Only the owner can mint.", "error")
        return redirect(url_for("index"))
    to = request.form.get("to", "").strip()
    try:
        amount = int(request.form.get("amount", "0"))
    except ValueError:
        flash("Amount must be a whole number.", "error")
        return redirect(url_for("admin_panel"))
    if amount <= 0:
        flash("Amount must be > 0.", "error")
        return redirect(url_for("admin_panel"))
    if not to:
        flash("Recipient address required.", "error")
        return redirect(url_for("admin_panel"))
    try:
        r = client.mint(_selected_account(), to, amount)
        flash(
            f"Minted {amount} {client.symbol()} to {to[:10]}… — tx {r['txHash'][:12]}…",
            "success",
        )
    except Exception as e:
        flash(f"Mint failed: {_reason(e)}", "error")
    return redirect(url_for("admin_panel"))


def _reason(exc: Exception) -> str:
    msg = str(exc)
    for marker in ("revert ", "execution reverted: ", "custom error "):
        if marker in msg:
            return msg.split(marker, 1)[1]
    return msg


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5002, debug=True)
