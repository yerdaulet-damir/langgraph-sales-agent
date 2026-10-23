"""Agent state definition.

Single source of truth for all data flowing through the sales agent graph.
State is tenant-agnostic — tenant context is injected via runtime config.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class SalesAgentState(TypedDict):
    """State for the sales agent graph.

    Attributes:
        messages: Conversation history. Uses add_messages reducer
                  so messages accumulate across nodes automatically.
        matched_products: Products found by the most recent search.
        product_images: Image URLs to send back to the user.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    matched_products: list[dict]
    product_images: list[str]
    channel: str
    channel_user_id: str
    # --- Nano (XNO) payment ---
    pending_invoice: dict  # {raw (decimal str), merchant, block_hash} of the open invoice
    confirmed_payment: bool  # True only after verify_nano_block == confirmed
    order_released: bool  # Set only by release_order after confirmed_payment
