"""
Flask UI for the ERC-721 Event Tickets dApp.

Routes:
  /                                events list (primary sale) + active resale market
  /switch-account                  POST: change active wallet
  /buy/<eventId>                   POST: primary mint
  /my-tickets                      tickets owned by the active wallet, with action buttons
  /transfer/<tokenId>              POST: free transferFrom
  /approve/<tokenId>               POST: approve(this contract, tokenId)  ← step 1 of resale
  /list/<tokenId>                  POST: listForResale(tokenId, price)    ← step 2 of resale
  /cancel/<tokenId>                POST: cancelResale
  /buy-resale/<tokenId>            POST: marketplace purchase
  /admin                           GET:  owner-only event creation + withdraw + balance
  /admin/create-event              POST: create new event
  /admin/withdraw                  POST: pull protocol fees to owner
  /metadata/<slug>/<tokenId>.json  GET:  off-chain metadata served from on-chain state
                                          (this is what tokenURI points to; in production we'd use IPFS)
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

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
    out = []
    for a in client.accounts:
        out.append(
            {
                "index": a.index,
                "address": a.address,
                "balanceEth": client.eth_balance(a.address) / 10**18,
                "isOwner": client.is_owner(a.address),
            }
        )
    return out


@app.context_processor
def _common():
    selected = _selected_account()
    return {
        "selected_account": selected,
        "is_owner": client.is_owner(selected),
        "account_options": _account_options(),
        "contract_address": client.address,
        "owner_address": client.owner,
    }


@app.post("/switch-account")
def switch_account():
    addr = request.form.get("account", "").strip()
    if addr and any(a.address == addr for a in client.accounts):
        session["account"] = addr
        flash(f"Switched to {addr[:10]}…", "info")
    return redirect(request.referrer or url_for("index"))


def _flash_tx(verb: str, r: dict) -> None:
    flash(
        f"{verb} — tx {r['txHash'][:12]}… block {r['blockNumber']}, gas {r['gasUsed']}",
        "success",
    )


def _enrich_event(e: dict) -> dict:
    return {**e, "priceEth": e["priceWei"] / 10**18}


def _enrich_ticket(t: dict, events_by_id: dict) -> dict:
    metadata = _read_metadata(t["tokenURI"])
    ev = events_by_id.get(t["eventId"], {})
    cap_wei = t["originalPriceWei"] * 2
    return {
        **t,
        "eventName": ev.get("name", f"#{t['eventId']}"),
        "originalPriceEth": t["originalPriceWei"] / 10**18,
        "listingPriceEth": t["listingPriceWei"] / 10**18,
        "capWei": cap_wei,
        "capEth": cap_wei / 10**18,
        "metadata": metadata,
    }


_METADATA_FIXTURES = {
    "local-night": {
        "description": "Local Night — a small-room concert at Sub Club, Glasgow.",
        "image": "https://placehold.co/600x400/1e293b/38bdf8?text=Local+Night",
        "venue": "Sub Club, Glasgow",
        "date": "2026-06-14T20:00:00Z",
        "attributes": [{"trait_type": "Tier", "value": "GA"}],
    },
    "tech-conf-2026": {
        "description": "Tech Conf 2026 — two days of talks at the Edinburgh ICC.",
        "image": "https://placehold.co/600x400/1e293b/34d399?text=Tech+Conf+2026",
        "venue": "Edinburgh International Conference Centre",
        "date": "2026-09-22T09:00:00Z",
        "attributes": [{"trait_type": "Tier", "value": "Standard"}],
    },
}


def _build_metadata(slug: str, token_id: int) -> dict:
    """Resolve a tokenURI to a JSON metadata document.

    On-chain we keep only the canonical state (eventId, seatNumber, originalPrice).
    Here we look up the same tokenId on the contract and combine it with the
    static event-level fixture to produce an OpenSea-compatible JSON. This is
    what an IPFS-pinned metadata service would do — we just compute it lazily.
    """
    summary = client._ticket_summary(token_id)
    fixture = _METADATA_FIXTURES.get(slug, {})
    events_by_id = {e["id"]: e for e in client.list_events()}
    ev = events_by_id.get(summary["eventId"], {})
    return {
        "name": f"{ev.get('name', 'Ticket')} — Seat {summary['seatNumber']}",
        "description": fixture.get("description", "Event ticket NFT."),
        "image": fixture.get("image"),
        "external_url": f"http://127.0.0.1:5003/my-tickets",
        "attributes": [
            {"trait_type": "Event ID", "value": summary["eventId"]},
            {"trait_type": "Seat", "value": summary["seatNumber"]},
            {"trait_type": "Original price (wei)", "value": str(summary["originalPriceWei"])},
            {"trait_type": "Venue", "value": fixture.get("venue", "TBA")},
            {"trait_type": "Date", "value": fixture.get("date", "TBA")},
            *fixture.get("attributes", []),
        ],
    }


def _read_metadata(uri: str) -> dict:
    """Resolve the JSON behind a tokenURI for inline display in templates.
    Re-uses the same _build_metadata logic so the page and the JSON endpoint
    always agree."""
    if not uri:
        return {}
    marker = "/metadata/"
    idx = uri.find(marker)
    if idx == -1:
        return {}
    rest = uri[idx + len(marker) :]  # "<slug>/<tokenId>.json"
    parts = rest.split("/")
    if len(parts) != 2 or not parts[1].endswith(".json"):
        return {}
    slug = parts[0]
    try:
        token_id = int(parts[1].removesuffix(".json"))
    except ValueError:
        return {}
    try:
        return _build_metadata(slug, token_id)
    except Exception:
        return {}


@app.get("/metadata/<slug>/<int:token_id>.json")
def metadata(slug: str, token_id: int):
    return jsonify(_build_metadata(slug, token_id))


@app.get("/")
def index():
    events = [_enrich_event(e) for e in client.list_events()]
    events_by_id = {e["id"]: e for e in events}
    listings = [_enrich_ticket(t, events_by_id) for t in client.listed_tickets()]
    return render_template("index.html", events=events, listings=listings)


@app.post("/buy/<int:event_id>")
def buy(event_id: int):
    event = next((e for e in client.list_events() if e["id"] == event_id), None)
    if event is None:
        flash("Event not found.", "error")
        return redirect(url_for("index"))
    try:
        r = client.buy_ticket(_selected_account(), event_id, event["priceWei"])
        _flash_tx(f"Minted ticket for '{event['name']}'", r)
    except Exception as e:
        flash(f"Buy failed: {_reason(e)}", "error")
    return redirect(url_for("my_tickets"))


@app.get("/my-tickets")
def my_tickets():
    addr = _selected_account()
    events_by_id = {e["id"]: e for e in client.list_events()}
    tickets = [_enrich_ticket(t, events_by_id) for t in client.my_tickets(addr)]
    return render_template("my_tickets.html", tickets=tickets, my_address=addr)


@app.post("/transfer/<int:token_id>")
def transfer(token_id: int):
    to = request.form.get("to", "").strip()
    if not to:
        flash("Recipient required.", "error")
        return redirect(url_for("my_tickets"))
    try:
        r = client.transfer(_selected_account(), to, token_id)
        _flash_tx(f"Transferred ticket #{token_id}", r)
    except Exception as e:
        flash(f"Transfer failed: {_reason(e)}", "error")
    return redirect(url_for("my_tickets"))


@app.post("/approve/<int:token_id>")
def approve(token_id: int):
    try:
        r = client.approve(_selected_account(), client.address, token_id)
        _flash_tx(f"Approved marketplace for ticket #{token_id}", r)
    except Exception as e:
        flash(f"Approve failed: {_reason(e)}", "error")
    return redirect(url_for("my_tickets"))


@app.post("/list/<int:token_id>")
def list_for_resale(token_id: int):
    try:
        price_eth = float(request.form.get("priceEth", "0"))
    except ValueError:
        flash("Invalid price.", "error")
        return redirect(url_for("my_tickets"))
    if price_eth <= 0:
        flash("Price must be > 0.", "error")
        return redirect(url_for("my_tickets"))
    price_wei = int(price_eth * 10**18)
    try:
        r = client.list_for_resale(_selected_account(), token_id, price_wei)
        _flash_tx(f"Listed ticket #{token_id} at {price_eth} ETH", r)
    except Exception as e:
        flash(f"List failed: {_reason(e)}", "error")
    return redirect(url_for("my_tickets"))


@app.post("/cancel/<int:token_id>")
def cancel(token_id: int):
    try:
        r = client.cancel_resale(_selected_account(), token_id)
        _flash_tx(f"Cancelled listing for ticket #{token_id}", r)
    except Exception as e:
        flash(f"Cancel failed: {_reason(e)}", "error")
    return redirect(url_for("my_tickets"))


@app.post("/buy-resale/<int:token_id>")
def buy_resale(token_id: int):
    # Re-read live to know the price + that it's still listed.
    summary = client._ticket_summary(token_id)
    if not summary["listed"]:
        flash("That ticket is no longer listed.", "error")
        return redirect(url_for("index"))
    try:
        r = client.buy_resale(_selected_account(), token_id, summary["listingPriceWei"])
        _flash_tx(f"Bought ticket #{token_id} from secondary market", r)
    except Exception as e:
        flash(f"Buy failed: {_reason(e)}", "error")
    return redirect(url_for("my_tickets"))


@app.get("/admin")
def admin_panel():
    if not client.is_owner(_selected_account()):
        flash("Admin panel is only for the contract owner.", "error")
        return redirect(url_for("index"))
    events = [_enrich_event(e) for e in client.list_events()]
    contract_balance_eth = client.eth_balance(client.address) / 10**18
    return render_template(
        "admin.html", events=events, contract_balance_eth=contract_balance_eth
    )


@app.post("/admin/create-event")
def admin_create_event():
    if not client.is_owner(_selected_account()):
        flash("Only the owner can create events.", "error")
        return redirect(url_for("index"))
    name = request.form.get("name", "").strip()
    base_uri = request.form.get("baseURI", "").strip()
    try:
        price_eth = float(request.form.get("priceEth", "0"))
        max_supply = int(request.form.get("maxSupply", "0"))
    except ValueError:
        flash("Invalid numeric input.", "error")
        return redirect(url_for("admin_panel"))
    if not name or not base_uri or price_eth <= 0 or max_supply <= 0:
        flash("Name, baseURI, price > 0, supply > 0 all required.", "error")
        return redirect(url_for("admin_panel"))
    try:
        r = client.create_event(
            _selected_account(), name, int(price_eth * 10**18), max_supply, base_uri
        )
        _flash_tx(f"Created event '{name}'", r)
    except Exception as e:
        flash(f"Create failed: {_reason(e)}", "error")
    return redirect(url_for("admin_panel"))


@app.post("/admin/withdraw")
def admin_withdraw():
    if not client.is_owner(_selected_account()):
        flash("Only the owner can withdraw.", "error")
        return redirect(url_for("index"))
    try:
        r = client.withdraw(_selected_account())
        _flash_tx("Withdrew protocol fees", r)
    except Exception as e:
        flash(f"Withdraw failed: {_reason(e)}", "error")
    return redirect(url_for("admin_panel"))


def _reason(exc: Exception) -> str:
    msg = str(exc)
    for marker in ("revert ", "execution reverted: ", "custom error "):
        if marker in msg:
            return msg.split(marker, 1)[1]
    return msg


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5003, debug=True)
