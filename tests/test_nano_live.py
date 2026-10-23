"""Opt-in live tests against a public Nano node. Read-only: nothing is signed or sent.

Skipped unless NANO_LIVE_TEST=1. NANO_LIVE_RPC overrides the node URL.

    NANO_LIVE_TEST=1 pytest tests/test_nano_live.py -v

The tests take a real, already-confirmed send from the ledger (one that paid
the well-known burn address, so the destination is fixed and public) and check
each rule against it: block format, destination, exact amount, confirmation,
and that a receive block is not accepted as the payment proof.
"""

import importlib
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("NANO_LIVE_TEST") != "1",
    reason="live Nano network test; set NANO_LIVE_TEST=1 to run",
)

mod = importlib.import_module("src.tools.verify_nano_block")

BURN = "nano_1111111111111111111111111111111111111111111111111111hifc8npp"
OTHER = "nano_3t6k35gi95xu6tergt6p69ck76ogmitsa8mnijtpxm9fkcm736xtoncuohr3"


@pytest.fixture(scope="module", autouse=True)
def rpc_url():
    url = os.environ.get("NANO_LIVE_RPC")
    if url:
        old, mod.RPC_URL = mod.RPC_URL, url
        yield
        mod.RPC_URL = old
    else:
        yield


@pytest.fixture(scope="module")
def live_send(rpc_url):
    pending = mod._rpc("receivable", {"account": BURN, "count": "1"})
    hashes = pending.get("blocks") or []
    if isinstance(hashes, dict):
        hashes = list(hashes)
    assert hashes, f"node returned no receivable sends: {pending}"
    block_hash = hashes[0]
    info = mod._rpc("block_info", {"json_block": "true", "hash": block_hash})
    assert "error" not in info, info
    return block_hash, info


def test_live_block_format(live_send):
    _, info = live_send
    assert info["contents"]["type"] == "state"
    assert info["subtype"] == "send"
    assert info["contents"]["link_as_account"] == BURN
    # block_account is the SENDER, which is why it must not be compared.
    assert info["block_account"] != BURN


def test_live_send_to_destination_is_confirmed(live_send):
    _, info = live_send
    assert info["confirmed"] == "true"
    assert mod.check_send_block(info, BURN, int(info["amount"])) == "confirmed"


def test_live_wrong_destination(live_send):
    _, info = live_send
    assert mod.check_send_block(info, OTHER, int(info["amount"])).startswith(
        "wrong-destination"
    )


def test_live_sender_as_merchant_is_refused(live_send):
    _, info = live_send
    result = mod.check_send_block(info, info["block_account"], int(info["amount"]))
    assert result.startswith("wrong-destination")


def test_live_exact_amount(live_send):
    _, info = live_send
    assert mod.check_send_block(info, BURN, int(info["amount"]) + 1).startswith(
        "amount-short"
    )


def test_live_tool_end_to_end(live_send):
    block_hash, info = live_send
    result = mod.verify_nano_block.invoke(
        {"block_hash": block_hash, "expected_raw": int(info["amount"])},
        config={"configurable": {"merchant_nano_address": BURN}},
    )
    assert result == "confirmed"


def test_live_receive_block_is_not_a_payment(live_send):
    _, info = live_send
    history = mod._rpc(
        "account_history",
        {"account": info["block_account"], "count": "50", "raw": "true"},
    )
    entries = history.get("history") or []
    # With raw=true, state blocks report type "state" and put send/receive in
    # "subtype"; without raw they report it in "type". Accept either spelling.
    receives = [
        e for e in entries if (e.get("subtype") or e.get("type")) == "receive"
    ]
    if not receives:
        pytest.skip("no receive block in the sender's recent history")
    rinfo = mod._rpc("block_info", {"json_block": "true", "hash": receives[0]["hash"]})
    if rinfo.get("contents", {}).get("type") != "state":
        pytest.skip("receive found is a legacy block, not a state block")
    assert rinfo["subtype"] == "receive"
    assert mod.check_send_block(rinfo, info["block_account"], 1).startswith("not-a-send")
