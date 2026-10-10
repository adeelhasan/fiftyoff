"""Flip estimate (arbitrage.py): pure arithmetic on stored prices; no network."""

from fiftyoff import arbitrage


def _offer(cond, price, ship=0, warehouse=False):
    return {"condition": cond, "isWarehouseDeal": warehouse, "offerCSV": [1000, price, ship]}


def test_other_used_skips_resale_new_and_dead_offers():
    p = {"offers": [_offer(2, 15000, warehouse=True),   # the Resale unit itself
                    _offer(1, 30000),                    # New
                    _offer(3, 18000, ship=599),          # used, with shipping
                    _offer(4, 17000),                    # used, but not live
                    _offer(5, 21000)],
         "liveOffersOrder": [0, 1, 2, 4]}
    assert arbitrage.other_used(p) == {"used_3p": 18599, "used_3p_n": 2}
    assert arbitrage.other_used({}) == {"used_3p": None, "used_3p_n": 0}


def test_estimate_exits_at_three_quarters_of_new():
    a = arbitrage.estimate(20000, 40000, resale_live=1)
    assert a["exit"] == 300 and a["sole"] and a["warn"] == []
    # eBay: 300 * (1 - 0.1325) - 0.40 - 200 * 1.08 = 43.85
    assert a["net"] == {"ebay": 44, "amazon": 31, "local": 84} and a["best"] == 44


def test_estimate_caps_under_other_used_and_warns():
    a = arbitrage.estimate(20000, 40000, used_3p=25000, resale_live=2)
    assert a["exit"] == 249 and a["warn"] == ["capped_by_used", "more_resale"] and not a["sole"]
    b = arbitrage.estimate(20000, 40000, used_3p=19000)
    assert "used_cheaper" in b["warn"] and b["best"] < 0


def test_estimate_needs_both_prices():
    assert arbitrage.estimate(None, 40000) is None and arbitrage.estimate(20000, None) is None
