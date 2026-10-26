"""Progressive gross markup for Avito only; Drom pricing is unchanged.

The rates apply to marginal portions of the *purchase cost*, not to the
whole purchase price. This avoids cheaper selling prices just above a tier.
Profit is gross, before Avito fees, delivery, refunds and tax.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, InvalidOperation

DEFAULT_TIERS = (
    (Decimal("2000"), Decimal("37")),
    (Decimal("5000"), Decimal("25")),
    (Decimal("10000"), Decimal("18")),
    (Decimal("20000"), Decimal("12")),
    (None, Decimal("9")),
)


def _decimal(value, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError(f"Invalid Avito pricing {label}: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"Non-finite Avito pricing {label}")
    return number


def progressive_price(cost, settings: dict | None = None) -> int:
    """Return selling price rounded upward to 50 RUB by default."""
    settings = settings or {}
    price = _decimal(cost, "cost")
    if price <= 0:
        raise ValueError("Avito purchase cost must be positive")
    round_to = _decimal(settings.get("round_up_to", 50), "round_up_to")
    if round_to <= 0:
        raise ValueError("Avito round_up_to must be positive")

    raw_tiers = settings.get("tiers")
    if raw_tiers is None:
        tiers = DEFAULT_TIERS
    else:
        if not isinstance(raw_tiers, list) or not raw_tiers:
            raise ValueError("Avito pricing tiers must be a nonempty list")
        tiers = []
        for entry in raw_tiers:
            if not isinstance(entry, dict) or "rate_percent" not in entry:
                raise ValueError("Invalid Avito pricing tier")
            cap = entry.get("up_to")
            tiers.append((None if cap is None else _decimal(cap, "up_to"),
                          _decimal(entry["rate_percent"], "rate_percent")))

    lower = Decimal("0")
    markup = Decimal("0")
    last_rate = None
    for index, (cap, rate) in enumerate(tiers):
        if rate < 0 or rate > 100:
            raise ValueError("Avito markup percentages must be between 0 and 100")
        if last_rate is not None and rate > last_rate:
            raise ValueError("Avito markup rates must not increase across tiers")
        if cap is None:
            if index != len(tiers) - 1:
                raise ValueError("Avito pricing open-ended tier must be last")
            upper = price
        else:
            if cap <= lower:
                raise ValueError("Avito pricing thresholds must increase")
            if index == len(tiers) - 1:
                raise ValueError("Avito pricing needs an open-ended final tier")
            upper = min(price, cap)
        if upper > lower:
            markup += (upper - lower) * rate / Decimal("100")
        if cap is not None:
            lower = cap
        last_rate = rate

    total = price + markup
    return int((total / round_to).to_integral_value(rounding=ROUND_CEILING) * round_to)
