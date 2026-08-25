from evaluation.fixtures.python.core.math_ops import add, multiply

def global_calculate(x: int) -> int:
    return add(x, 10)

def process_with_param_shadow(x: int, add: int) -> int:
    # Parameter 'add' shadows imported 'add' function
    return add + x

def process_with_local_assign(x: int) -> int:
    # Local variable 'multiply' shadows imported 'multiply' function
    multiply = 42
    return multiply + x

def process_with_comprehension(items: list[int]) -> int:
    # Comprehension variable 'add' must NOT leak to outer scope
    squares = [add * 2 for add in items]
    # Outer call to imported add
    return add(sum(squares), 1)

def process_with_local_import(x: int) -> int:
    # Function-local import
    from evaluation.fixtures.python.core.math_ops import discount
    return int(discount(float(x), 0.2))

class Worker:
    def method_normal(self, val: int) -> int:
        return multiply(val, 2)

    def method_with_param_shadow(self, val: int, add: int) -> int:
        # Parameter 'add' shadows imported 'add'
        return add + val
