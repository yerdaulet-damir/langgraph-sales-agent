"""Node: execute tool calls made by the assistant.

Takes the last AI message's tool_calls, runs each tool,
and returns ToolMessage results. Routes back to assistant, or to
release_order once a Nano payment for the open invoice is verified.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from src.state.agent_state import SalesAgentState
from src.tools import ALL_TOOLS
from src.tools.create_nano_invoice import xno_to_raw


# Build a lookup map: tool_name → tool_function
_TOOL_MAP = {t.name: t for t in ALL_TOOLS}


async def tool_executor_node(
    state: SalesAgentState,
    config: RunnableConfig,
) -> Command[Literal["assistant", "release_order"]]:
    """Execute all tool calls from the last message, then return to assistant."""
    last_message = state["messages"][-1]
    results: list[ToolMessage] = []
    update: dict = {}
    invoice = state.get("pending_invoice") or {}
    newly_confirmed = False

    for call in last_message.tool_calls:
        tool_fn = _TOOL_MAP.get(call["name"])

        if tool_fn is None:
            results.append(
                ToolMessage(
                    content=f"Error: Unknown tool '{call['name']}'",
                    tool_call_id=call["id"],
                )
            )
            continue

        args = dict(call["args"])
        if call["name"] == "verify_nano_block":
            # Verify against the invoice held in state, never an amount the
            # model supplies, and refuse when there is no open invoice.
            if not str(invoice.get("raw") or "").isdigit():
                results.append(
                    ToolMessage(
                        content="no-open-invoice: create a Nano invoice first",
                        tool_call_id=call["id"],
                    )
                )
                continue
            args["expected_raw"] = int(invoice["raw"])

        # Invoke the tool with its arguments + config (for tenant context)
        try:
            output = await tool_fn.ainvoke(args, config=config)
        except Exception as e:
            output = f"Error executing {call['name']}: {e}"

        if call["name"] == "create_nano_invoice" and str(output).startswith("Pay "):
            # Raw is kept as a decimal string: it exceeds 64 bits, which the
            # checkpointer cannot serialise as an integer.
            invoice = {
                "raw": str(xno_to_raw(str(args["amount_xno"]))),
                "merchant": config["configurable"]["merchant_nano_address"],
                "block_hash": None,
            }
            update["pending_invoice"] = invoice
            update["confirmed_payment"] = False
            update["order_released"] = False
            newly_confirmed = False
        elif call["name"] == "verify_nano_block" and output == "confirmed":
            invoice = {**invoice, "block_hash": str(args["block_hash"]).strip()}
            update["pending_invoice"] = invoice
            update["confirmed_payment"] = True
            newly_confirmed = True

        results.append(
            ToolMessage(
                content=str(output),
                tool_call_id=call["id"],
            )
        )

    return Command(
        update={**update, "messages": results},
        goto="release_order" if newly_confirmed else "assistant",
    )
