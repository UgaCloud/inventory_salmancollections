from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONEY = Decimal("0.01")
QUANTITY = Decimal("0.001")
COST = Decimal("0.0001")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(MONEY, rounding=ROUND_HALF_UP)


def qty(value) -> Decimal:
    return Decimal(value or 0).quantize(QUANTITY, rounding=ROUND_HALF_UP)


def unit_cost(value) -> Decimal:
    return Decimal(value or 0).quantize(COST, rounding=ROUND_HALF_UP)


def to_decimal(value, *, field="value"):
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid number for {field}.")


def divide(numerator, denominator, places=4):
    if not denominator:
        return Decimal("0")
    quantum = Decimal(1).scaleb(-places)
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        quantum, rounding=ROUND_HALF_UP
    )
