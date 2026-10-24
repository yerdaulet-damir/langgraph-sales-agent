"""Graph-level gate for Nano (XNO) payments.

An order is released only by ``release_order_node``, and the graph only routes
there after ``tool_executor_node`` has seen ``verify_nano_block`` return
"confirmed" for the invoice held in state. The node re-checks the state itself,
so a wrong route still cannot release an unpaid order.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from src.state.agent_state import SalesAgentState


def payment_verified(state: SalesAgentState) -> bool:
    """True only when the open invoice has a confirmed send block on record."""
    invoice = state.get("pending_invoice") or {}
    return (
        state.get("confirmed_payment") is True
        and str(invoice.get("raw") or "").isdigit()
        and int(invoice["raw"]) > 0
        and bool(invoice.get("block_hash"))
    )


async def release_order_node(
    state: SalesAgentState,
    config: RunnableConfig,
) -> Command[Literal["assistant"]]:
    """Mark the order released, but only if the payment was verified."""
    return Command(
        update={"order_released": payment_verified(state)},
        goto="assistant",
    )
