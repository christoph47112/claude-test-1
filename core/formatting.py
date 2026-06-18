"""Deutsche Zahlenformatierung (Tausenderpunkt, Komma, €)."""
from __future__ import annotations

import math


def _is_na(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def de_number(v, decimals: int = 0) -> str:
    """1234567.8 -> '1.234.568' (decimals=0) / '1.234.567,80' (decimals=2)."""
    if _is_na(v):
        return "–"
    s = f"{float(v):,.{decimals}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def euro(v, decimals: int = 0) -> str:
    if _is_na(v):
        return "–"
    return f"{de_number(v, decimals)} €"


def percent(v, decimals: int = 1, with_sign: bool = False) -> str:
    """v als Anteil (0.023 -> '2,3 %'). with_sign zeigt + bei positiv."""
    if _is_na(v):
        return "–"
    val = float(v) * 100
    sign = "+" if (with_sign and val > 0) else ""
    return f"{sign}{de_number(val, decimals)} %"


def delta_euro(v, decimals: int = 0) -> str:
    if _is_na(v):
        return "–"
    sign = "+" if float(v) > 0 else ""
    return f"{sign}{euro(v, decimals)}"
