"""All tools available to the sales agent."""

from src.tools.search_products import search_products
from src.tools.search_by_image import search_by_image
from src.tools.get_promotions import get_promotions
from src.tools.send_product_image import send_product_image
from src.tools.create_nano_invoice import create_nano_invoice
from src.tools.verify_nano_block import verify_nano_block

ALL_TOOLS = [
    search_products,
    search_by_image,
    get_promotions,
    send_product_image,
    create_nano_invoice,
    verify_nano_block,
]

__all__ = [
    "search_products",
    "search_by_image",
    "get_promotions",
    "send_product_image",
    "create_nano_invoice",
    "verify_nano_block",
    "ALL_TOOLS",
]
