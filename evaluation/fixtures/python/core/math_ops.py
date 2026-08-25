"""Top-level math and utility helpers."""

def add(a: int, b: int) -> int:
    return a + b

def multiply(a: int, b: int) -> int:
    return a * b

def compute_tax(amount: float, rate: float) -> float:
    base = multiply(int(amount), 1)
    return base * rate

def discount(price: float, percentage: float) -> float:
    tax = compute_tax(price, 0.1)
    return price - (tax * percentage)
