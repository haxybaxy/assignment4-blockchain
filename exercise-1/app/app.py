"""
Flask UI for the Vending Machine dApp (network-aware).

Routes match Assignment 3 verbatim. The only A4 addition is that successful
transactions now include an Etherscan link when running on a public network.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for

from web3_client import build_client_from_env

# Load .env from this app/ dir AND the project root, so the same .env at the
# project's exercise-1/ root can drive both Hardhat and Flask.
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
    out = []
    for a in client.accounts:
        eth = client.eth_balance(a.address) / 10**18
        out.append(
            {
                "index": a.index,
                "address": a.address,
                "balanceEth": eth,
                "isOwner": client.is_owner(a.address),
            }
        )
    return out


@app.context_processor
def _inject_common():
    selected = _selected_account()
    return {
        "selected_account": selected,
        "is_owner": client.is_owner(selected),
        "account_options": _account_options(),
        "contract_address": client.address,
        "owner_address": client.owner,
        "network_name": client.network_name,
        "chain_id": client.chain_id,
        "is_public_chain": client.mode == "public",
        "contract_url": client.address_url(client.address),
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
    products = client.list_products()
    for p in products:
        p["priceEth"] = p["priceWei"] / 10**18
    return render_template("index.html", products=products)


def _flash_tx(verb: str, receipt: dict) -> None:
    msg = f"{verb} — tx {receipt['txHash'][:12]}… block {receipt['blockNumber']}, gas {receipt['gasUsed']}"
    if receipt.get("txUrl"):
        msg += f" · {receipt['txUrl']}"
    flash(msg, "success")


@app.post("/buy/<int:product_id>")
def buy(product_id: int):
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        flash("Quantity must be a number.", "error")
        return redirect(url_for("index"))
    if quantity <= 0:
        flash("Quantity must be at least 1.", "error")
        return redirect(url_for("index"))

    product = next((p for p in client.list_products() if p["id"] == product_id), None)
    if product is None:
        flash("Product not found.", "error")
        return redirect(url_for("index"))

    total_wei = product["priceWei"] * quantity
    try:
        receipt = client.purchase(_selected_account(), product_id, quantity, total_wei)
    except Exception as e:
        flash(f"Purchase failed: {_reason(e)}", "error")
        return redirect(url_for("index"))

    _flash_tx(f"Bought {quantity} × {product['name']}", receipt)
    return redirect(url_for("my_items"))


@app.get("/my-items")
def my_items():
    addr = _selected_account()
    receipts = client.receipts_of(addr)
    products = {p["id"]: p for p in client.list_products()}
    totals: dict[int, int] = {}
    for r in receipts:
        totals[r["productId"]] = totals.get(r["productId"], 0) + r["quantity"]

    summary = []
    for pid, qty in sorted(totals.items()):
        p = products.get(pid, {"name": f"#{pid}"})
        summary.append({"productId": pid, "name": p.get("name", f"#{pid}"), "quantity": qty})

    enriched = []
    for r in receipts:
        p = products.get(r["productId"], {"name": f"#{r['productId']}"})
        enriched.append(
            {
                **r,
                "productName": p.get("name"),
                "unitPriceEth": r["unitPrice"] / 10**18,
                "totalEth": (r["unitPrice"] * r["quantity"]) / 10**18,
            }
        )
    return render_template("owned.html", summary=summary, receipts=enriched)


@app.get("/admin")
def admin_panel():
    if not client.is_owner(_selected_account()):
        flash("Admin panel is only available to the contract owner.", "error")
        return redirect(url_for("index"))
    products = client.list_products()
    for p in products:
        p["priceEth"] = p["priceWei"] / 10**18
    contract_balance_eth = client.eth_balance(client.address) / 10**18
    return render_template("admin.html", products=products, contract_balance_eth=contract_balance_eth)


@app.post("/admin/add")
def admin_add():
    if not client.is_owner(_selected_account()):
        flash("Only the owner can add products.", "error")
        return redirect(url_for("index"))
    name = request.form.get("name", "").strip()
    try:
        price_eth = float(request.form.get("priceEth", "0"))
        stock = int(request.form.get("stock", "0"))
    except ValueError:
        flash("Invalid numeric input.", "error")
        return redirect(url_for("admin_panel"))
    if not name or price_eth <= 0 or stock < 0:
        flash("Name required, price > 0, stock >= 0.", "error")
        return redirect(url_for("admin_panel"))
    try:
        r = client.add_product(_selected_account(), name, int(price_eth * 10**18), stock)
        _flash_tx("Product added", r)
    except Exception as e:
        flash(f"Failed: {_reason(e)}", "error")
    return redirect(url_for("admin_panel"))


@app.post("/admin/restock")
def admin_restock():
    if not client.is_owner(_selected_account()):
        flash("Only the owner can restock.", "error")
        return redirect(url_for("index"))
    try:
        product_id = int(request.form["productId"])
        amount = int(request.form["amount"])
    except (KeyError, ValueError):
        flash("Invalid restock input.", "error")
        return redirect(url_for("admin_panel"))
    try:
        r = client.restock(_selected_account(), product_id, amount)
        _flash_tx("Restocked", r)
    except Exception as e:
        flash(f"Failed: {_reason(e)}", "error")
    return redirect(url_for("admin_panel"))


@app.post("/admin/price")
def admin_price():
    if not client.is_owner(_selected_account()):
        flash("Only the owner can update prices.", "error")
        return redirect(url_for("index"))
    try:
        product_id = int(request.form["productId"])
        new_price_eth = float(request.form["priceEth"])
    except (KeyError, ValueError):
        flash("Invalid price input.", "error")
        return redirect(url_for("admin_panel"))
    if new_price_eth <= 0:
        flash("Price must be > 0.", "error")
        return redirect(url_for("admin_panel"))
    try:
        r = client.update_price(_selected_account(), product_id, int(new_price_eth * 10**18))
        _flash_tx("Price updated", r)
    except Exception as e:
        flash(f"Failed: {_reason(e)}", "error")
    return redirect(url_for("admin_panel"))


@app.post("/admin/active")
def admin_active():
    if not client.is_owner(_selected_account()):
        flash("Only the owner can toggle products.", "error")
        return redirect(url_for("index"))
    try:
        product_id = int(request.form["productId"])
        active = request.form.get("active") == "true"
    except (KeyError, ValueError):
        flash("Invalid input.", "error")
        return redirect(url_for("admin_panel"))
    try:
        r = client.set_active(_selected_account(), product_id, active)
        _flash_tx("Status updated", r)
    except Exception as e:
        flash(f"Failed: {_reason(e)}", "error")
    return redirect(url_for("admin_panel"))


@app.post("/admin/withdraw")
def admin_withdraw():
    if not client.is_owner(_selected_account()):
        flash("Only the owner can withdraw.", "error")
        return redirect(url_for("index"))
    try:
        r = client.withdraw(_selected_account())
        _flash_tx("Withdrawn", r)
    except Exception as e:
        flash(f"Failed: {_reason(e)}", "error")
    return redirect(url_for("admin_panel"))


def _reason(exc: Exception) -> str:
    msg = str(exc)
    for marker in ("revert ", "execution reverted: ", "custom error "):
        if marker in msg:
            return msg.split(marker, 1)[1]
    return msg


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
