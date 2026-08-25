"""Application entry points exercising the ground-truth scenarios."""
from core.service import compute_total
from core.labels import format_label as code_label  # alias import
from core import service


def build_invoice(price: float, quantity: int) -> str:
    # Ground truth: direct call -> core.service.compute_total
    total = compute_total(price, quantity)
    return service.format_label("invoice", total)


def build_code_label(prefix: str, code: int) -> str:
    # Ground truth: alias call -> core.labels.format_label (imported as code_label)
    return code_label(prefix, code)


def dispatch(handler_name: str):
    # Ground truth: dynamic/reflection gap. The callee is resolved at
    # runtime via getattr; static analysis must NOT report a direct edge.
    handler = getattr(service, handler_name)
    return handler(1.0, 1)
