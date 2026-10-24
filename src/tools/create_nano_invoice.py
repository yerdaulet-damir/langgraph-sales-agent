"""Tool: create a Nano (XNO) invoice the customer can pay instantly and feeless."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

# 1 XNO = 10^30 raw. Amounts travel as raw (int) so there is never float ambiguity.
XNO_RAW = 10 ** 30
# A receivable below a node's default receive_minimum can sit unconfirmed forever.
RECEIVE_MINIMUM_RAW = 10 ** 24  # == 0.000001 XNO, the node default


def xno_to_raw(xno: str) -> int:
    """Convert a decimal XNO string to raw using exact integer math.

    Never use a float here: ``round(1.0 * 10**30)`` is off by ~2e12 raw because
    10^30 is not representable as a float. ``"1" -> 10^30``, ``"0.0001" -> 10^26``.
    """
    if xno.count(".") > 1:
        raise ValueError(f"not a decimal: {xno!r}")
    whole, _, frac = xno.partition(".")
    whole = (whole or "0").strip()
    if not whole.isdigit():
        raise ValueError(f"not a non-negative decimal: {xno!r}")
    raw = int(whole) * XNO_RAW
    if frac:
        if not frac.isdigit():
            raise ValueError(f"not a non-negative decimal: {xno!r}")
        frac = (frac + "0" * (30 - len(frac))) if len(frac) < 30 else frac[:30]
        raw += int(frac)  # 30 decimal places IS raw, so int(frac) is the raw fraction
    return raw


@tool
def create_nano_invoice(
    amount_xno: str, config: RunnableConfig
) -> str:
    """Create a Nano (XNO) invoice for an order.

    Use this when the customer is ready to pay and you need a destination to
    receive a feeless, instant settlement in XNO. Returns a plain nano_ address
    and an exact raw amount the customer pays and the merchant verifies.

    Args:
        amount_xno: The order total in XNO as a decimal string (e.g. "0.0001").
    """
    try:
        raw = xno_to_raw(amount_xno)
    except ValueError as exc:
        return f"bad-amount: {exc}"
    if raw <= 0:
        return "Amount must be positive."
    if raw < RECEIVE_MINIMUM_RAW:
        return (
            f"Amount {amount_xno} XNO is below the smallest receivable "
            f"({RECEIVE_MINIMUM_RAW / XNO_RAW} XNO). Raise it to at least that."
        )
    merchant = config["configurable"]["merchant_nano_address"]
    return f"Pay {raw} raw ({amount_xno} XNO) to {merchant}. Confirm with the block hash of your send."