"""Flip estimate (admins only, 2026-10-09): could we buy this Resale unit and resell it at a profit?

Deterministic arithmetic only (rule 7). Every number here is a tunable guess, not a measurement: the point is
to log an estimate per deal now and compare it later with what actually sold, then retune (ARB_VERSION).

Exit price: a share of the New reference, capped just under the cheapest other used offer on Amazon (Keepa's
own used price includes the Resale unit itself, so it can't be the benchmark: 2026-10-09, 1,340 of 1,678 deals
had used == Resale price). Net = exit after the channel's fees, minus what we pay (with sales tax).
"""

ARB_VERSION = "x0.1"

EXIT_SHARE_OF_NEW = 0.75   # a like-new used unit sells for ~3/4 of New; at 50% off that's the midpoint
UNDERCUT_CENTS = 100       # list $1 under the cheapest other used offer
PURCHASE_TAX = 0.08        # sales tax on the Resale purchase (no resale certificate yet)
CHANNELS = {               # fee share of the sale price, flat cents per sale (fulfilment, inbound, payment)
    "ebay": (0.1325, 40),          # final value fee + per-order fee; buyer pays shipping
    "amazon": (0.15, 800),         # referral + FBA fulfilment + inbound shipping; no return to Amazon after
    "local": (0.0, 0),             # Facebook Marketplace pickup: no fees, no shipping
}
PRIMARY = "ebay"          # the channel the sort and headline use (local is best-case, Amazon the hardest)
USED = range(2, 6)         # Keepa offer conditions 2-5: Used Like New .. Acceptable


def other_used(p: dict) -> dict:
    """The cheapest live used offer that isn't a Resale (Warehouse) unit, with shipping, and how many there are."""
    live = set(p.get("liveOffersOrder") or [])
    prices = []
    for i, o in enumerate(p.get("offers") or []):
        csv = o.get("offerCSV") or []
        if o.get("isWarehouseDeal") or i not in live or o.get("condition") not in USED or len(csv) < 3:
            continue
        if csv[-2] is not None and csv[-2] > 0:
            prices.append(csv[-2] + max(csv[-1] or 0, 0))
    return {"used_3p": min(prices, default=None), "used_3p_n": len(prices)}


def estimate(resale_cents: int | None, new_cents: int | None, used_3p: int | None = None,
             resale_live: int | None = None) -> dict | None:
    """Exit price and net per channel in dollars, plus why it might not work. None without both prices."""
    if not resale_cents or not new_cents:
        return None
    exit_c = round(new_cents * EXIT_SHARE_OF_NEW)
    capped = used_3p is not None and used_3p - UNDERCUT_CENTS < exit_c
    if capped:
        exit_c = used_3p - UNDERCUT_CENTS
    cost = resale_cents * (1 + PURCHASE_TAX)
    net = {k: round((exit_c * (1 - fee) - flat - cost) / 100) for k, (fee, flat) in CHANNELS.items()}
    warn = []
    if used_3p is not None and used_3p <= resale_cents:
        warn.append("used_cheaper")       # another seller already sells it used for less than we'd pay
    elif capped:
        warn.append("capped_by_used")     # other used offers set the exit, not the New price
    if resale_live and resale_live > 1:
        warn.append("more_resale")        # buying this unit leaves another Resale unit on the page
    return {"v": ARB_VERSION, "exit": round(exit_c / 100), "net": net, "best": net[PRIMARY],
            "used_3p": None if used_3p is None else round(used_3p / 100), "sole": resale_live == 1, "warn": warn}
