"""Label formatting utilities (same-name symbol #2)."""


def format_label(prefix: str, code: int) -> str:
    """Same-name symbol #2: code label formatting. Distinct from core.service.format_label."""
    return f"[{prefix}] #{code}"
