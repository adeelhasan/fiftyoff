"""Sizes of size-dependent deals (D59), read deterministically from each unit's title.

Every Resale unit is one child ASIN, so one size, and its title nearly always ends with it ("..., Burgundy, 8 E US",
"..., 12 Short", "..., 32W x 30L"). A size is a product attribute, not a price: no model call, no Keepa field. The
rater's stored size (appeal.size, rated per parent) is only a fallback for single-unit cards.

Four systems, each matched against the sizes a visitor keeps on their device:
  letter  XXS..5XL (combos like "L/XL" match either)
  num     numbered clothing sizes (dresses, women's pants), 0-30
  waist   waist, with the inseam length when the title gives one ("32x30")
  shoe    a shoe size with the wearer (men / women / kids, from the title) and a width (wide / narrow)
"""

from __future__ import annotations

import re

SIZES_VERSION = "z0.1"
LETTERS = ["XXS", "XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL"]
_LETTER = {}
for _v, _ws in {"XXS": "xxs xxsmall 2xs", "XS": "xs xsmall extrasmall", "S": "s small sm", "M": "m medium md med",
                "L": "l large lg", "XL": "xl xlarge extralarge 1x 1xl", "2XL": "xxl 2xl xxlarge 2x 2xlarge",
                "3XL": "xxxl 3xl 3x 3xlarge xxxlarge", "4XL": "4xl 4x 4xlarge xxxxl", "5XL": "5xl 5x 5xlarge"}.items():
    for _w in _ws.split():
        _LETTER[_w] = _v
FIT_WORDS = r"(?:tall|short|long|regular|reg|petite|plus|plus size|big|big & tall|slim|husky|r|p|t)"
SHOE_SHELVES = {"sneakers-running-shoes", "dress-shoes-heels", "sandals-flats", "boots", "sport-shoes", "workwear"}
WAIST_SHELVES = {"jeans", "pants-shorts", "workwear", "suits-blazers"}

_WAIST = re.compile(r"^w?\s*(\d{2})\s*w?\s*(?:x|/|\s)\s*l?\s*(\d{2})\s*l?(?:\s+" + FIT_WORDS + r")?$")
_NUM = re.compile(r"^(?:us\s*)?(\d{1,2})\s*(?:" + FIT_WORDS + r"|w)?$")
_SHOE = re.compile(r"^(\d{1,2}(?:\.5)?)(?:\s*[-/]\s*\d{1,2}(?:\.5)?)?\s*(.*)$")
_WIDE = re.compile(r"\b(?:w|ww|xw|xxw|xxxw|wide|x-?wide|xx-?wide|3x-?wide|extra wide|e{2,6}|[2-6]e|xx)\b|^w$")
_NARROW = re.compile(r"\b(?:n|narrow|aa+|ss)\b")
_SHOE_REST = re.compile(r"(?:(?:[a-e]|m|n|w|ww|xw|xxw|xxxw|wide|narrow|medium|regular|x-?wide|xx-?wide|3x-?wide|extra wide|"
                        r"e{2,6}|[2-6]e|xx|xxl|us|men|women|men's|women's|little kid|big kid|kid|toddler|infant|youth|"
                        r"c/d|b/m|d/m|dm|h|s|aa+)[\s,-]*)+")
_KIDS = re.compile(r"\b(?:kids?|little kid|big kid|toddler|youth|infant|baby|boys?|girls?)\b|\bboy's\b|\bgirl's\b")
_WOMEN = re.compile(r"\b(?:women'?s?|womens|ladies|woman's)\b")
_MEN = re.compile(r"\b(?:men'?s?|mens|man's)\b")


def _letter(s: str) -> list[str] | None:
    t = re.sub(r"\s+" + FIT_WORDS + r"$", "", s)
    one = _LETTER.get(t.replace("-", "").replace(" ", ""))
    if one:
        return [one]
    parts = re.split(r"\s*/\s*", t) if "/" in t else re.split(r"\s*-\s*", t)
    vals = [_LETTER.get(p.replace("-", "").replace(" ", "")) for p in parts]
    if len(parts) == 2 and all(vals):
        return sorted(set(vals), key=LETTERS.index)  # "L/XL", "S-M"
    return None


def _wearer(title: str, rest: str) -> str | None:
    for text in (rest, title.lower()):
        if _KIDS.search(text):
            return "kids"
        if _WOMEN.search(text):
            return "women"
        if _MEN.search(text):
            return "men"
    return None


def parse_text(s: str | None, shelf: str | None, title: str = "") -> dict | None:
    """One size string ("9.5 Wide", "32W x 30L", "X-Large Tall", "12P") -> a size dict, or None."""
    if not s:
        return None
    t = s.strip().lower().replace("“", '"').replace("”", '"').strip(" .")
    t = re.sub(r"\s*\((?:[^)]*)\)$", "", t).strip()  # "9.5 XX (5E)" -> "9.5 XX"
    t = t.strip("()[] ")  # "(Black, X-Large)" splits into "x-large)"
    t = re.sub(r"\s+us$", "", t).strip()
    if not t or len(t) > 24:
        return None
    m = _WAIST.match(t)
    if m and 23 <= int(m[1]) <= 60 and 26 <= int(m[2]) <= 38:
        return _size("waist", m[1], length=m[2])
    if shelf in SHOE_SHELVES:
        m = _SHOE.match(t)
        if m and 0 < float(m[1]) <= 17 and not re.search(r"\b(?:eu|cm|mm|uk)\b", m[2]):
            rest = m[2]
            if rest and not _SHOE_REST.fullmatch(rest):  # "8 White" (a model number, then a colour) is no size
                return None
            width = "wide" if _WIDE.search(rest) else "narrow" if _NARROW.search(rest) else None
            if shelf == "workwear" and not width and not rest and "." not in m[1]:
                pass  # a bare number on workwear is more likely a numbered garment; fall through
            else:
                v = m[1].removesuffix(".0")
                return _size("shoe", v, wearer=_wearer(title, rest), width=width)
    letters = _letter(t)
    if letters:
        return _size("letter", letters[0], alts=letters)
    m = _NUM.match(t)
    if m and int(m[1]) <= 60:
        n = int(m[1])
        if n >= 23 and (shelf in WAIST_SHELVES or n > 30):
            return _size("waist", str(n))
        if n <= 30:
            return _size("num", str(n))
    return None


def parse(title: str | None, shelf: str | None) -> dict | None:
    """A unit's size from its title: the last comma segment, then the one before it, then the title's last words."""
    if not title:
        return None
    segs = [x.strip() for x in title.split(",") if x.strip()]
    cands = segs[-1:-3:-1] if len(segs) > 1 else []
    words = title.split()
    cands += [" ".join(words[-k:]) for k in (3, 2, 1) if len(words) > k]
    for c in cands:
        z = parse_text(c, shelf, title)
        if z:
            return z
    return None


def _size(system: str, v: str, alts: list[str] | None = None, length: str | None = None, wearer: str | None = None,
          width: str | None = None) -> dict:
    return {"system": system, "v": v, "alts": alts or [v], "length": length, "wearer": wearer, "width": width,
            "label": label(system, v, alts, length, wearer, width)}


def label(system, v, alts=None, length=None, wearer=None, width=None) -> str:
    if system == "letter":
        return "/".join(alts or [v])
    if system == "num":
        return f"Size {v}"
    if system == "waist":
        return f"{v}×{length}" if length else f"Waist {v}"
    who = {"men": "Men's ", "women": "Women's ", "kids": "Kids "}.get(wearer or "", "")
    return f"{who}{v}{' Wide' if width == 'wide' else ' Narrow' if width == 'narrow' else ''}"


def wanted(prefs: dict) -> bool:
    return any(prefs.get(k) for k in ("letter", "num", "waist", "shoe"))


def matches(z: dict, prefs: dict) -> bool:
    """Does one unit's size match the visitor's sizes? prefs: letter / num / waist / length / shoe, each a set;
    shoe entries are "men-10.5". A shoe whose wearer the title doesn't say matches a men's or women's choice."""
    sysm = z["system"]
    if sysm == "letter":
        return bool(set(z["alts"]) & prefs.get("letter", set()))
    if sysm == "num":
        return z["v"] in prefs.get("num", set())
    if sysm == "waist":
        lengths = prefs.get("length", set())
        return z["v"] in prefs.get("waist", set()) and (not lengths or not z["length"] or z["length"] in lengths)
    if sysm == "shoe":
        shoes = prefs.get("shoe", set())
        if z["wearer"]:
            return f"{z['wearer']}-{z['v']}" in shoes
        return f"men-{z['v']}" in shoes or f"women-{z['v']}" in shoes
    return False


def facet_key(z: dict) -> tuple[str, str] | list[tuple[str, str]]:
    """Where a size counts in the size picker: (group, value). Shoes count under their wearer, or both when unknown."""
    if z["system"] == "shoe":
        return [(f"shoe-{w}", z["v"]) for w in ([z["wearer"]] if z["wearer"] else ["men", "women"])]
    if z["system"] == "letter":
        return [("letter", a) for a in z["alts"]]
    if z["system"] == "waist":
        return [("waist", z["v"])] + ([("length", z["length"])] if z["length"] else [])
    return [(z["system"], z["v"])]


def order(group: str, v: str) -> tuple:
    return (LETTERS.index(v),) if group == "letter" and v in LETTERS else (float(v),) if re.fullmatch(r"\d+(\.\d+)?", v) else (999,)
