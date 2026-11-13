from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from country_map import resolve


@dataclass
class CapacityHit:
    phone_code: str
    price: float
    iso: str
    name: str
    raw_line: str


# Common price patterns: $0.30, 0.30$, 0.30 $, Free:$0.30, → $0.30, etc.
PRICE_RE = re.compile(
    r"(?:Free:|New:|\$\s*)(\d+(?:\.\d+)?)\s*\$?|(\d+(?:\.\d+)?)\s*\$",
    re.IGNORECASE,
)
# Phone codes: +964, +1-US, +1, +1809
CODE_RE = re.compile(
    r"\+(\d{1,4}(?:-\w+)?)",
)


def _extract_price(text: str) -> float | None:
    # Prefer explicit Free: or first $ amount that is not 0.00 spam
    for m in PRICE_RE.finditer(text):
        val = float(m.group(1) or m.group(2) or 0)
        if val > 0:
            return val
    return None


def parse_generic(text: str) -> list[CapacityHit]:
    """
    Universal parser.
    Looks for lines (or adjacent lines) that contain a +code and a price.
    Handles:
      🇦🇫 +93 Afghanistan
      Free:$0.30|New:$0.30|Spam:$0.00|300s
    and
      [🇺🇿]+998–UZ: 0.45$
    and
      🇫🇰FK +500 → $8
    and
      🇮🇶 Iraq +964:
      Free:1.2$|New:1.2$|Time:600s
    """
    hits: list[CapacityHit] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    i = 0
    while i < len(lines):
        line = lines[i]
        codes = CODE_RE.findall(line)
        price = _extract_price(line)

        # price may be on next line
        if codes and price is None and i + 1 < len(lines):
            price = _extract_price(lines[i + 1])

        if codes and price is not None and price > 0:
            for raw_code in codes:
                code = "+" + raw_code
                iso, name = resolve(code)
                hits.append(
                    CapacityHit(
                        phone_code=code,
                        price=price,
                        iso=iso,
                        name=name,
                        raw_line=line,
                    )
                )
        i += 1

    # dedupe by phone_code keeping highest price (conservative)
    best: dict[str, CapacityHit] = {}
    for h in hits:
        if h.phone_code not in best or h.price > best[h.phone_code].price:
            best[h.phone_code] = h
    return list(best.values())


def parse_tglion(text: str) -> list[CapacityHit]:
    """TGLion style: [🇺🇿]+998–UZ: 0.45$  or  … → Full"""
    hits = parse_generic(text)
    # Drop anything marked Full (same line or adjacent)
    return [h for h in hits if "full" not in h.raw_line.lower()]


PARSERS = {
    "CM_Receiver6_Bot": parse_generic,
    "Crazy_TimeAcc2_robot": parse_generic,
    "tg_get2_bot": parse_generic,
    "sttar1_bot": parse_generic,
    "TBUNLIMITED2_BOT": parse_generic,
    "TGLionAPI_bot": parse_tglion,
}


def parse_for_bot(bot_username: str, text: str) -> list[CapacityHit]:
    key = bot_username.lstrip("@")
    fn = PARSERS.get(key, parse_generic)
    return fn(text)
