"""Offline tests for the order-release gate: the RPC is mocked, nothing is sent."""

import asyncio
import importlib
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from src.graphs import sales_graph
from src.nodes.payment_gate import payment_verified, release_order_node
from src.nodes.tool_executor import tool_executor_node

verify_mod = importlib.import_module("src.tools.verify_nano_block")

MERCHANT = "nano_3merchant1111111111111111111111111111111111111111111111111111"
OTHER = "nano_1other11111111111111111111111111111111111111111111111111111111"
SENDER = "nano_1sender1111111111111111111111111111111111111111111111111111111"
HASH = "A" * 64
INVOICE_XNO = "0.0001"
INVOICE_RAW = 10**26
CONFIG = {"configurable": {"merchant_nano_address": MERCHANT, "thread_id": "t"}}


def send_block(**overrides):
    info = {
        "block_account": SENDER,
        "amount": str(INVOICE_RAW),
        "confirmed": "true",
        "subtype": "send",
        "contents": {"type": "state", "account": SENDER, "link_as_account": MERCHANT},
    }
    info.update(overrides)
    return info


def mock_rpc(monkeypatch, response):
    calls = []

    def fake_rpc(method, params):
        calls.append((method, params))
        return response

    monkeypatch.setattr(verify_mod, "_rpc", fake_rpc)
    return calls


def tool_call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def run_tools(state):
    return asyncio.run(tool_executor_node(state, CONFIG))


def open_invoice_state():
    cmd = run_tools({"messages": [tool_call("create_nano_invoice", {"amount_xno": INVOICE_XNO})]})
    return {k: v for k, v in cmd.update.items() if k != "messages"}


def verify(state, args):
    msg = tool_call("verify_nano_block", args, call_id="c2")
    return run_tools({**state, "messages": [msg]})


# --- tool executor ----------------------------------------------------------


def test_invoice_opens_pending_invoice_and_resets_gate():
    state = open_invoice_state()
    assert state["pending_invoice"] == {
        "raw": str(INVOICE_RAW),
        "merchant": MERCHANT,
        "block_hash": None,
    }
    assert state["confirmed_payment"] is False
    assert state["order_released"] is False


def test_verify_without_invoice_is_refused_without_rpc(monkeypatch):
    calls = mock_rpc(monkeypatch, send_block())
    cmd = verify({}, {"block_hash": HASH, "expected_raw": INVOICE_RAW})
    assert cmd.goto == "assistant"
    assert cmd.update["messages"][0].content.startswith("no-open-invoice")
    assert "confirmed_payment" not in cmd.update
    assert calls == []


def test_confirmed_payment_routes_to_release(monkeypatch):
    mock_rpc(monkeypatch, send_block())
    cmd = verify(open_invoice_state(), {"block_hash": HASH, "expected_raw": INVOICE_RAW})
    assert cmd.update["messages"][0].content == "confirmed"
    assert cmd.update["confirmed_payment"] is True
    assert cmd.update["pending_invoice"]["block_hash"] == HASH
    assert cmd.goto == "release_order"


def test_model_cannot_lower_the_invoiced_amount(monkeypatch):
    # The send pays 1 raw; the model claims the invoice was 1 raw. The executor
    # verifies against the invoice in state, so the order is not released.
    mock_rpc(monkeypatch, send_block(amount="1"))
    cmd = verify(open_invoice_state(), {"block_hash": HASH, "expected_raw": 1})
    assert cmd.update["messages"][0].content.startswith("amount-short")
    assert "confirmed_payment" not in cmd.update
    assert cmd.goto == "assistant"


def test_wrong_destination_is_not_released(monkeypatch):
    contents = {"type": "state", "account": SENDER, "link_as_account": OTHER}
    mock_rpc(monkeypatch, send_block(contents=contents))
    cmd = verify(open_invoice_state(), {"block_hash": HASH, "expected_raw": INVOICE_RAW})
    assert cmd.update["messages"][0].content.startswith("wrong-destination")
    assert cmd.goto == "assistant"


def test_block_account_equal_to_merchant_is_not_enough(monkeypatch):
    # The old bug: matching block_account. A block whose account is the
    # merchant but whose destination is elsewhere must not pass.
    contents = {"type": "state", "account": MERCHANT, "link_as_account": OTHER}
    mock_rpc(monkeypatch, send_block(block_account=MERCHANT, contents=contents))
    cmd = verify(open_invoice_state(), {"block_hash": HASH, "expected_raw": INVOICE_RAW})
    assert cmd.update["messages"][0].content.startswith("wrong-destination")
    assert cmd.goto == "assistant"


def test_receive_subtype_is_not_released(monkeypatch):
    mock_rpc(monkeypatch, send_block(subtype="receive"))
    cmd = verify(open_invoice_state(), {"block_hash": HASH, "expected_raw": INVOICE_RAW})
    assert cmd.update["messages"][0].content.startswith("not-a-send")
    assert cmd.goto == "assistant"


def test_unconfirmed_block_is_not_released(monkeypatch):
    mock_rpc(monkeypatch, send_block(confirmed="false"))
    cmd = verify(open_invoice_state(), {"block_hash": HASH, "expected_raw": INVOICE_RAW})
    assert cmd.update["messages"][0].content.startswith("not-yet")
    assert cmd.goto == "assistant"


# --- release node -------------------------------------------------------------


def test_release_node_refuses_unverified_state():
    for state in (
        {},
        {"confirmed_payment": False, "pending_invoice": {"raw": str(INVOICE_RAW), "block_hash": HASH}},
        {"confirmed_payment": True, "pending_invoice": {"raw": str(INVOICE_RAW), "block_hash": None}},
        {"confirmed_payment": True, "pending_invoice": {}},
    ):
        assert payment_verified(state) is False
        cmd = asyncio.run(release_order_node(state, CONFIG))
        assert cmd.update == {"order_released": False}


def test_release_node_releases_verified_state():
    state = {"confirmed_payment": True, "pending_invoice": {"raw": str(INVOICE_RAW), "block_hash": HASH}}
    cmd = asyncio.run(release_order_node(state, CONFIG))
    assert cmd.update == {"order_released": True}


# --- whole graph with a scripted assistant (no LLM) ---------------------------


def scripted_graph(monkeypatch, verify_args):
    script = [
        tool_call("create_nano_invoice", {"amount_xno": INVOICE_XNO}, "c1"),
        tool_call("verify_nano_block", verify_args, "c2"),
        AIMessage(content="done"),
    ]

    async def fake_assistant(state, config) -> Command[Literal["tools", "__end__"]]:
        msg = script.pop(0)
        return Command(update={"messages": [msg]}, goto="tools" if msg.tool_calls else "__end__")

    monkeypatch.setattr(sales_graph, "assistant_node", fake_assistant)
    return sales_graph.compile_sales_graph()


# Tool-call args are checkpointed with the AI message, and msgpack cannot hold
# integers over 64 bits, so the scripted model sends raw amounts as strings.
def run_graph(graph):
    return asyncio.run(graph.ainvoke({"messages": [HumanMessage(content="buy")]}, CONFIG))


def test_graph_releases_order_only_after_verified_payment(monkeypatch):
    mock_rpc(monkeypatch, send_block())
    final = run_graph(scripted_graph(monkeypatch, {"block_hash": HASH, "expected_raw": str(INVOICE_RAW)}))
    assert final["confirmed_payment"] is True
    assert final["order_released"] is True


def test_graph_does_not_release_unconfirmed_payment(monkeypatch):
    mock_rpc(monkeypatch, send_block(confirmed="false"))
    final = run_graph(scripted_graph(monkeypatch, {"block_hash": HASH, "expected_raw": str(INVOICE_RAW)}))
    assert final["confirmed_payment"] is False
    assert final["order_released"] is False


def test_graph_does_not_release_short_payment(monkeypatch):
    mock_rpc(monkeypatch, send_block(amount=str(INVOICE_RAW - 1)))
    final = run_graph(scripted_graph(monkeypatch, {"block_hash": HASH, "expected_raw": "1"}))
    assert final["confirmed_payment"] is False
    assert final["order_released"] is False
