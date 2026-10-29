"""Closed quantity-kind unit conversion registry (small approved teaching subset).

QUDT IRIs are annotations; this module does NOT claim a complete QUDT ontology/reasoner.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext

CONVERSIONS = {
    ("vibration_velocity", "mm/s"): (Decimal("1"),Decimal("0"),"mm/s","http://qudt.org/vocab/unit/MilliM-PER-SEC"),
    ("vibration_velocity", "m/s"): (Decimal("1000"),Decimal("0"),"mm/s","http://qudt.org/vocab/unit/M-PER-SEC"),
    ("temperature", "degC"): (Decimal("1"),Decimal("0"),"degC","http://qudt.org/vocab/unit/DEG_C"),
    ("temperature", "K"): (Decimal("1"),Decimal("-273.15"),"degC","http://qudt.org/vocab/unit/K"),
}


def normalize(value: str | int | float, kind: str, unit: str) -> tuple[Decimal,str]:
    entry = CONVERSIONS.get((kind,unit))
    if entry is None:
        raise ValueError(f"Incompatible or unsupported quantity kind/unit: {kind}/{unit}")
    try:
        number = Decimal(str(value))
    except (InvalidOperation,ValueError) as exc:
        raise ValueError("Invalid numeric quantity") from exc
    if not number.is_finite():
        raise ValueError("Non-finite measurement forbidden")
    with localcontext() as context:
        context.prec = 28
        result = number*entry[0]+entry[1]
    return result,entry[2]


def compare_upper(value: str | int | float, unit: str, kind: str,
                  limit_value: str | int | float, limit_unit: str) -> tuple[bool,str,str]:
    observed, target_unit = normalize(value,kind,unit)
    limit, limit_target = normalize(limit_value,kind,limit_unit)
    if target_unit != limit_target:
        raise ValueError("Cannot compare different physical quantity kinds")
    return observed > limit,format(observed,"f"),target_unit
