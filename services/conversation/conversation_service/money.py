"""Formatting only. No arithmetic happens in this service — the core service owns it."""
from __future__ import annotations


def format_inr(paise: int | None) -> str:
    if paise is None:
        return "-"
    value = paise / 100
    sign = "-" if value < 0 else ""
    whole, _, frac = f"{abs(value):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    return f"₹{sign}{whole}.{frac}"
