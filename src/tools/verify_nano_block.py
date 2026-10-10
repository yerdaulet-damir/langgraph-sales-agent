"""Tool: confirm a Nano (XNO) payment by verifying the customer's send block.

Nano is verification == settlement: a confirmed send block whose destination
is the merchant's nano_ address IS the settlement. No facilitator, no gas, no
token account, no relay. The merchant needs only its public address.

The invoice from ``create_nano_invoice`` asks the customer to confirm with the
hash of their SEND block. That block lives on the customer's account chain, so
its ``block_account`` is the sender, not the merchant. Verification therefore
reads that one block from the public ledger and checks the block itself:

  1. it is a state block with subtype ``send``;
  2. its destination (``link_as_account``) is the merchant's address;
  3. its amount in raw is at least the invoiced raw amount; and
  4. the network has confirmed it (``confirmed == "true"``).

It does not require the merchant to have published a receive block: once a
send is confirmed the funds are the merchant's, receivable whenever its wallet
pockets them. Every missing field, unexpected value or RPC failure returns a
non-"confirmed" answer (fail closed).

This proves a payment to the merchant happened. It does not by itself stop a
customer reusing one old send hash for a second order; a deployer that needs
that should record each confirmed hash and refuse repeats.
"""

from __future__ import annotations

import json
import re
import urllib.request

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

# Public Nano RPC (no key required for read-only block_info).
# Swap for a configured node URL if the deployer prefers one.
RPC_URL = "https://rpc.nano.to"
# rpc.nano.to refuses requests with no User-Agent (HTTP 403), so send one.
_USER_AGENT = "langgraph-sales-agent-nano-leg/1.0"

_BLOCK_HASH = re.compile(r"^[0-9A-Fa-f]{64}$")


def _rpc(method: str, params: dict):
    body = json.dumps({"action": method, **params}).encode()
    req = urllib.request.Request(
        RPC_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _account_key(address: str | None) -> str | None:
    """Compare addresses without the nano_/xrb_ prefix (same key, two spellings)."""
    if not isinstance(address, str):
        return None
    for prefix in ("nano_", "xrb_"):
        if address.startswith(prefix):
            return address[len(prefix):]
    return None


def check_send_block(info, merchant: str, expected_raw: int) -> str:
    """Return "confirmed" only if ``info`` (a block_info result) pays the merchant.

    Pure function so it can be tested without a network.
    """
    if not isinstance(info, dict):
        return "could-not-verify: unexpected RPC response"
    if info.get("error"):
        return "not-yet: block not found (still pending or invalid hash)"

    contents = info.get("contents")
    if not isinstance(contents, dict):
        contents = {}

    subtype = info.get("subtype")
    if subtype != "send":
        return (
            f"not-a-send: block subtype is {subtype!r}; confirm with the hash "
            "of the send block that paid the invoice"
        )

    destination = info.get("link_as_account") or contents.get("link_as_account")
    merchant_key = _account_key(merchant)
    if merchant_key is None or _account_key(destination) != merchant_key:
        return "wrong-destination: the send was not to the merchant address"

    try:
        amount_raw = int(str(info["amount"]))
    except (KeyError, TypeError, ValueError):
        return "could-not-verify: block has no readable amount"
    if amount_raw < expected_raw:
        return (
            f"amount-short: got {amount_raw} raw, invoice required "
            f"{expected_raw} raw. Do not release the order."
        )

    if info.get("confirmed") != "true":
        return "not-yet: send block is not confirmed by the network yet"

    return "confirmed"


@tool
def verify_nano_block(
    block_hash: str, expected_raw: int, config: RunnableConfig
) -> str:
    """Confirm a Nano payment from the hash of the customer's send block.

    Returns "confirmed" only when that block is a network-confirmed send to the
    merchant address of at least the invoiced raw amount. Any other answer
    means the order must not be released yet.

    Args:
        block_hash: The hash of the send block the customer made to pay.
        expected_raw: The raw amount the invoice required.
    """
    merchant = config["configurable"]["merchant_nano_address"]
    if not isinstance(block_hash, str) or not _BLOCK_HASH.match(block_hash.strip()):
        return "bad-hash: expected a 64-character hex block hash"
    try:
        expected = int(expected_raw)
    except (TypeError, ValueError):
        return "could-not-verify: invoice amount is not an integer raw value"
    if expected <= 0:
        return "could-not-verify: invoice amount must be positive"
    try:
        info = _rpc("block_info", {"json_block": "true", "hash": block_hash.strip()})
    except Exception as exc:  # network / RPC failure is not a confirmation
        return f"could-not-verify: {exc}"
    return check_send_block(info, merchant, expected)
