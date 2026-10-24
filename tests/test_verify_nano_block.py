"""Offline tests for verify_nano_block: the RPC is mocked, nothing is sent."""

import importlib

import pytest

# src.tools re-exports the tool under the module's name, so import the module itself.
mod = importlib.import_module("src.tools.verify_nano_block")

MERCHANT = "nano_3merchant1111111111111111111111111111111111111111111111111111"
OTHER = "nano_1other11111111111111111111111111111111111111111111111111111111"
SENDER = "nano_1sender1111111111111111111111111111111111111111111111111111111"
HASH = "A" * 64
INVOICE_RAW = 10**26  # 0.0001 XNO
CONFIG = {"configurable": {"merchant_nano_address": MERCHANT}}


def send_block(**overrides):
    info = {
        "block_account": SENDER,  # a send block belongs to the SENDER
        "amount": str(INVOICE_RAW),
        "confirmed": "true",
        "subtype": "send",
        "contents": {
            "type": "state",
            "account": SENDER,
            "link_as_account": MERCHANT,
        },
    }
    info.update(overrides)
    return info


def run(monkeypatch, response, expected_raw=INVOICE_RAW, block_hash=HASH):
    calls = []

    def fake_rpc(method, params):
        calls.append((method, params))
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(mod, "_rpc", fake_rpc)
    result = mod.verify_nano_block.invoke(
        {"block_hash": block_hash, "expected_raw": expected_raw}, config=CONFIG
    )
    return result, calls


def test_valid_send_to_merchant_is_confirmed(monkeypatch):
    result, calls = run(monkeypatch, send_block())
    assert result == "confirmed"
    assert calls == [("block_info", {"json_block": "true", "hash": HASH})]


def test_overpayment_is_confirmed(monkeypatch):
    result, _ = run(monkeypatch, send_block(amount=str(INVOICE_RAW + 1)))
    assert result == "confirmed"


def test_xrb_prefix_matches_same_account(monkeypatch):
    contents = {"type": "state", "link_as_account": "xrb_" + MERCHANT[5:]}
    result, _ = run(monkeypatch, send_block(contents=contents))
    assert result == "confirmed"


def test_wrong_destination(monkeypatch):
    contents = {"type": "state", "account": SENDER, "link_as_account": OTHER}
    result, _ = run(monkeypatch, send_block(contents=contents))
    assert result.startswith("wrong-destination")


def test_missing_destination(monkeypatch):
    result, _ = run(monkeypatch, send_block(contents={"type": "state"}))
    assert result.startswith("wrong-destination")


def test_short_amount(monkeypatch):
    result, _ = run(monkeypatch, send_block(amount=str(INVOICE_RAW - 1)))
    assert result.startswith("amount-short")


def test_missing_amount(monkeypatch):
    info = send_block()
    del info["amount"]
    result, _ = run(monkeypatch, info)
    assert result.startswith("could-not-verify")


@pytest.mark.parametrize("confirmed", ["false", None, True])
def test_unconfirmed(monkeypatch, confirmed):
    info = send_block(confirmed=confirmed)
    if confirmed is None:
        del info["confirmed"]
    result, _ = run(monkeypatch, info)
    assert result.startswith("not-yet")


def test_receive_block_is_refused(monkeypatch):
    # The merchant's own receive block: block_account IS the merchant, but it is
    # not the customer's send, so it is not accepted as the payment proof.
    info = send_block(
        subtype="receive",
        block_account=MERCHANT,
        contents={"type": "state", "account": MERCHANT, "link": "B" * 64},
    )
    result, _ = run(monkeypatch, info)
    assert result.startswith("not-a-send")


def test_missing_subtype_is_refused(monkeypatch):
    info = send_block()
    del info["subtype"]
    result, _ = run(monkeypatch, info)
    assert result.startswith("not-a-send")


def test_block_not_found(monkeypatch):
    result, _ = run(monkeypatch, {"error": "Block not found"})
    assert result.startswith("not-yet")


def test_rpc_error_fails_closed(monkeypatch):
    result, _ = run(monkeypatch, OSError("connection refused"))
    assert result.startswith("could-not-verify")


def test_non_dict_response_fails_closed(monkeypatch):
    result, _ = run(monkeypatch, ["unexpected"])
    assert result.startswith("could-not-verify")


def test_bad_hash_makes_no_rpc_call(monkeypatch):
    result, calls = run(monkeypatch, send_block(), block_hash="not-a-hash")
    assert result.startswith("bad-hash")
    assert calls == []
