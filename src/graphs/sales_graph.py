"""Sales agent graph assembly.

Wires together the assistant and tool_executor nodes into a
StateGraph with persistence. This is the core reusable graph
that serves all tenants.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START

from src.nodes.assistant import assistant_node
from src.nodes.payment_gate import release_order_node
from src.nodes.tool_executor import tool_executor_node
from src.state.agent_state import SalesAgentState


def build_sales_graph() -> StateGraph:
    """Build the sales agent graph (uncompiled).

    Graph structure:
        START → assistant → (tool_calls?) → tools → assistant → ... → END
                                              tools → release_order → assistant
                                              (only after a verified payment)

    Routing is handled inside nodes via Command — no conditional
    edge functions needed.
    """
    builder = StateGraph(SalesAgentState)

    # Add nodes
    builder.add_node("assistant", assistant_node)
    builder.add_node("tools", tool_executor_node)
    builder.add_node("release_order", release_order_node)

    # Entry point
    builder.add_edge(START, "assistant")

    # NOTE: No explicit edges between assistant ↔ tools.
    # Routing is done via Command inside each node:
    #   assistant → Command(goto="tools") or Command(goto="__end__")
    #   tools     → Command(goto="assistant"), or Command(goto="release_order")
    #               only when verify_nano_block confirmed the open invoice
    #   release_order → Command(goto="assistant")

    return builder


def compile_sales_graph():
    """Compile the graph with in-memory checkpointer.

    Returns a compiled graph ready to invoke with:
        graph.invoke(
            {"messages": [("user", "hello")]},
            config={"configurable": {"thread_id": "...", "tenant_id": "..."}}
        )
    """
    builder = build_sales_graph()
    checkpointer = InMemorySaver()
    return builder.compile(checkpointer=checkpointer)
