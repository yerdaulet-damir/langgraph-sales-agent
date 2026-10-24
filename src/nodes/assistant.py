"""Node: LLM assistant — the core chat node.

Loads tenant config, builds the system prompt, binds tools,
and invokes the model. Uses Command for routing: if the LLM
makes tool calls → go to "tools", otherwise → END.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from src.config.llm_provider import create_llm
from src.config.tenant_config import get_tenant
from src.state.agent_state import SalesAgentState
from src.tools import ALL_TOOLS


def _build_system_prompt(tenant_id: str, channel: str | None = None) -> str:
    """Build a system prompt from the tenant's config."""
    tc = get_tenant(tenant_id)
    agent = tc.agent

    products_hint = (
        "You have tools to search products, find promotions, "
        "send product images, and find similar items by image description.\n\n"
        "CRITICAL RULES FOR TOOLS:\n"
        "- ALWAYS call search_products FIRST when a customer asks about products, "
        "categories, flowers, bouquets, or anything related to the catalog.\n"
        "- NEVER describe, list, or suggest products from your own knowledge. "
        "You MUST use the tools to find real products.\n"
        "- If search returns no results, say so honestly — do NOT invent categories or items.\n"
        "- To show product photos, ALWAYS call the send_product_image tool with the product_id. "
        "NEVER paste image URLs directly into your text response. "
        "NEVER use markdown image syntax like ![](url). "
        "The send_product_image tool handles rendering on the customer's device.\n"
        "- When the customer says 'покажи', 'фото', 'show', or similar — "
        "call send_product_image for each relevant product.\n"
        "- For a Nano (XNO) payment, call create_nano_invoice, then verify_nano_block "
        "with the hash of the customer's send block. NEVER tell the customer the "
        "order is paid or released unless verify_nano_block returned exactly 'confirmed'."
    )

    channel_hint = f"You are chatting on {channel}.\n\n" if channel else ""

    return (
        f"You are {agent.name}, a {agent.role} at {tc.business_name}.\n\n"
        f"{agent.personality}\n\n"
        f"{channel_hint}"
        f"## Rules\n"
        + "\n".join(f"- {r}" for r in agent.rules)
        + f"\n\n## Important\n{products_hint}\n"
        f"\n## Language\n"
        f"You MUST respond ONLY in: {tc.language}. "
        f"If language is 'ru', respond in Russian (NOT Kazakh, NOT English). "
        f"Match the customer's language only if they explicitly write in another language.\n"
    )


async def assistant_node(
    state: SalesAgentState,
    config: RunnableConfig,
) -> Command[Literal["tools", "__end__"]]:
    """Invoke the LLM and route based on whether it made tool calls."""
    tenant_id = config["configurable"]["tenant_id"]
    tc = get_tenant(tenant_id)

    # Create provider-agnostic LLM from tenant config
    model = create_llm(tc).bind_tools(ALL_TOOLS)

    # Prepare messages: system prompt + conversation history
    channel = state.get("channel")
    system = SystemMessage(content=_build_system_prompt(tenant_id, channel))
    messages = [system] + state["messages"]

    # Invoke
    response = await model.ainvoke(messages, config=config)

    # Route: tool calls → tools node, otherwise → end
    if response.tool_calls:
        return Command(
            update={"messages": [response]},
            goto="tools",
        )

    return Command(
        update={"messages": [response]},
        goto="__end__",
    )
