import pytest

from fiftyoff import analysis
from fiftyoff.keepa import decode_csv, keepa_to_unix, unix_to_keepa
from tests.fixtures import build


def test_keepa_time_roundtrip():
    # Documented example: 7661010 -> 1753500600000 ms
    assert keepa_to_unix(7661010) * 1000 == 1753500600000
    assert unix_to_keepa(keepa_to_unix(7661010)) == 7661010


def test_decode_csv_pairs():
    assert decode_csv([1, 100, 5, -1]) == [(1, 100), (5, -1)]
    assert decode_csv(None) == []


def _rows():
    page = build.deal_page()["deals"]
    names = dict(zip(page["categoryIds"], page["categoryNames"]))
    return {r.asin: r for r in (analysis.deal_row(d, names, 0) for d in page["dr"]) if r}


def test_strictest_reference_wins():
    rows = _rows()
    assert rows["B0KITCHEN1"].strict == pytest.approx(0.55)
    assert rows["B0KITCHEN1"].keepa_ref_match == "amazon_now"
    # 90-day avg new is lower than today's prices, so the strict discount is only 40%
    assert rows["B0FITNESS1"].strict_key == "new_avg90"
    assert rows["B0FITNESS1"].strict == pytest.approx(0.40)
    # No Amazon offer (-1) is ignored, not treated as a price
    assert rows["B0ELEC0001"].discounts["amazon_now"] is None
    assert rows["B0ELEC0001"].keepa_ref_match is None


def test_census_summary_counts_inflation_and_misleading_claims():
    s = analysis.census_summary(list(_rows().values()))
    assert s["asins"] == 7 and s["parents"] == 6
    assert s["reported50"] == 7
    assert s["reported50_strict_below50"] == 2  # fitness (40%) and monitor (33%)


def _result():
    resp = build.product()
    return analysis.analyze_product(resp["products"][0], build.NOW, 180, category="Kitchen")


def test_observation_gaps():
    r = _result()
    assert r.gaps["median_gap_min"] == 60 and r.gaps["max_gap_min"] == 60
    assert r.csv9_aligned_with_obs == 1.0
    assert r.ref_coverage == pytest.approx(1.0)


def test_episodes_at_50_percent():
    eps = _result().aggregate_episodes[0.5]
    assert [e.end_reason for e in eps] == ["offer_disappeared", "offer_disappeared", "price_rose"]
    e1, e2, e3 = eps
    assert (e1.lifespan_min, e1.lifespan_max, e1.lifespan_band, e1.confidence) == (120, 240, "1–6 hr", "HIGH")
    assert e2.lifespan_band is None  # 0–120 min straddles bands: no false precision
    assert e3.lifespan_band == "6+ hr"


def test_right_censored_episode_makes_no_lifespan_claim():
    eps = _result().aggregate_episodes[0.4]
    assert eps[-1].end is None and eps[-1].lifespan_band is None and eps[-1].confidence == "OPEN"


def test_offer_level_uses_last_seen():
    r = _result()
    assert r.offer_episodes[0.5] == 1
    assert r.offer_conditions_in_episodes[0.5] == {"Used - Like New": 1}
    assert r.saving_basis_new == 20000
    assert r.live_warehouse_offer is False


def test_usability_and_decision():
    r = _result()
    assert r.recurrence_usable and r.lifespan_usable
    assert analysis.suggest_decision(7, [r]) == ("GO", "recurrence-usable 1/1 (100%), lifespan-usable 1/1 (100%)")
    assert analysis.suggest_decision(0, [r])[0] == "STOP / REASSESS"


def test_sparse_observations_are_not_recurrence_usable():
    resp = build.product()
    p = resp["products"][0]
    t0 = build.NOW - 180 * build.DAY
    p["csv"][15] = [t0, 5, t0 + 3 * build.DAY, 5, build.NOW, 5]  # a look every few days at best
    r = analysis.analyze_product(p, build.NOW, 180)
    assert not r.recurrence_usable
    assert any("median observation gap" in x for x in r.recurrence_reasons)


def test_resale_profile_on_fixture():
    from fiftyoff import presence
    p = build.product()["products"][0]
    r = presence.resale_profile(p, build.NOW, 180, (0.3, 0.5))
    assert r.episodes[0.5] == 3 and r.units_seen == 1 and r.units_gone == 1
    assert 0 < r.presence_share < 0.1  # three short-ish episodes plus the $120 tail
    assert r.live_resale is False
