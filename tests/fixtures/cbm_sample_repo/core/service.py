"""Core service layer for the sample fixture repo."""

TAX_RATE = 0.1


def compute_total(price: float, quantity: int) -> float:
    """Direct-call target: price * quantity with tax."""
    subtotal = price * quantity
    return round(subtotal * (1 + TAX_RATE), 2)


def format_label(name: str, total: float) -> str:
    """Same-name symbol #1: service-side label formatting."""
    return f"{name}: {total:.2f} USD"
