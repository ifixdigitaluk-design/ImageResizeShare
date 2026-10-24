"""Length / area units for wall work (internally everything is in metres)."""
from __future__ import annotations

M_PER_IN = 0.0254
M_PER_FT = 0.3048

# key: (label shown in combos, metres per unit)
LENGTH_UNITS = {
    "m": ("m", 1.0),
    "cm": ("cm", 0.01),
    "mm": ("mm", 0.001),
    "ft": ("feet", M_PER_FT),
    "in": ("inches", M_PER_IN),
    "ftin": ("ft + in", M_PER_FT),
}
UNIT_KEYS = ("m", "cm", "mm", "ftin", "ft", "in")
DECIMALS = {"m": 2, "cm": 1, "mm": 0, "ft": 2, "in": 1, "ftin": 2}


def to_unit(m: float, unit: str) -> float:
    return m / LENGTH_UNITS[unit][1]


def from_unit(v: float, unit: str) -> float:
    return v * LENGTH_UNITS[unit][1]


def ft_in(m: float, frac: int = 0) -> str:
    """4.20 m -> 13' 9\" (rounded to the nearest inch or 1/2, 1/4 inch)."""
    total_in = m / M_PER_IN
    step = 1.0 / frac if frac else 1.0
    total_in = round(total_in / step) * step
    feet = int(total_in // 12)
    inches = total_in - feet * 12
    if inches >= 12 - 1e-9:
        feet, inches = feet + 1, 0.0
    if frac and abs(inches - round(inches)) > 1e-9:
        whole = int(inches)
        part = inches - whole
        n = round(part * frac)
        from math import gcd
        g = gcd(n, frac)
        txt = f"{whole} {n // g}/{frac // g}" if whole else f"{n // g}/{frac // g}"
    else:
        txt = f"{int(round(inches))}"
    if feet == 0:
        return f'{txt}"'
    return f"{feet}' {txt}\""


def fmt(m: float, unit: str = "m", decimals: int | None = None, with_unit: bool = True) -> str:
    """Format a length in metres: '4.20 m', '420.0 cm', '13\\' 9\"', '165.4 in'."""
    if unit == "ftin":
        return ft_in(m)
    d = DECIMALS[unit] if decimals is None else decimals
    v = to_unit(m, unit)
    s = f"{v:.{d}f}"
    if not with_unit:
        return s
    sym = {"m": "m", "cm": "cm", "mm": "mm", "ft": "ft", "in": "in"}[unit]
    return f"{s} {sym}"


def fmt_short(m: float, unit: str = "m") -> str:
    """Compact label for dimension chains: '0.35', '1.40' (m) / '35' (cm) / 1' 2\"."""
    if unit == "ftin":
        return ft_in(m)
    d = {"m": 2, "cm": 0, "mm": 0, "ft": 2, "in": 0}[unit]
    return f"{to_unit(m, unit):.{d}f}"


def fmt_size(w: float, h: float, unit: str = "m") -> str:
    if unit == "ftin":
        return f"{ft_in(w)} × {ft_in(h)}"
    return f"{fmt(w, unit, with_unit=False)} × {fmt(h, unit)}"


def area_m2(w: float, h: float) -> float:
    return max(0.0, w) * max(0.0, h)


def fmt_area(a_m2: float, unit: str = "m2") -> str:
    if unit == "sqft":
        return f"{a_m2 / (M_PER_FT ** 2):.1f} sq ft"
    return f"{a_m2:.2f} m²"


def fmt_area_both(a_m2: float, primary: str = "m2") -> str:
    a, b = ("m2", "sqft") if primary == "m2" else ("sqft", "m2")
    return f"{fmt_area(a_m2, a)} ({fmt_area(a_m2, b)})"


def parse_length(text: str, unit: str = "m") -> float:
    """Parse '4.2', '420cm', '13\\' 9\"', '13ft 9in', '165 in' -> metres. Raises ValueError."""
    import re
    t = text.strip().lower().replace("″", '"').replace("′", "'").replace("’", "'").replace("”", '"')
    if not t:
        raise ValueError("empty")
    t = re.sub(r"(\d),(\d{1,2})(?!\d)", r"\1.\2", t)      # 4,2 m (decimal comma) – but not 1,200
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:'|ft|feet|foot)\s*(?:(\d+(?:\.\d+)?)\s*(?:\"|in|inch|inches)?)?", t)
    if m:
        return float(m.group(1)) * M_PER_FT + float(m.group(2) or 0) * M_PER_IN
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(mm|cm|m|in|inch|inches|\"|ft|feet)?", t)
    if not m:
        raise ValueError(text)
    v = float(m.group(1))
    u = m.group(2)
    if u is None:
        return from_unit(v, "ft" if unit == "ftin" else unit)
    u = {"inch": "in", "inches": "in", '"': "in", "feet": "ft"}.get(u, u)
    return from_unit(v, u)
