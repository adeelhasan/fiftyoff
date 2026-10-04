"""Curation (D36): the listing predicate the `unlisted` view mirrors, and admin changes."""

import pytest

from fiftyoff.curation import apply, listed

TAGS = ("featured", "newsletter")


@pytest.mark.parametrize("vis, status, decided, ref, want", [
    # auto: the rules decide
    ("auto", None, None, 10000, True),          # never held
    ("auto", "cleared", None, 10000, True),
    ("auto", "pending", None, 10000, False),
    (None, "pending", None, 10000, False),      # no curation row = auto
    # approved: listed while held, as long as the reference stays within 20% of the baseline
    ("approved", "pending", 10000, 11900, True),
    ("approved", "pending", 10000, 12000, True),   # exactly 20%: still within
    ("approved", "pending", 10000, 12100, False),  # moved up: lapsed
    ("approved", "pending", 10000, 7900, False),   # moved down: lapsed
    ("approved", "pending", None, 10000, False),   # no baseline fails closed
    ("approved", "pending", 10000, None, False),
    ("approved", "cleared", 10000, 50000, True),   # not held: the approval doesn't matter
    ("approved", None, None, None, True),
    # hidden: never
    ("hidden", None, None, 10000, False),
    ("hidden", "cleared", None, 10000, False),
    ("hidden", "pending", None, 10000, False),
])
def test_listed_truth_table(vis, status, decided, ref, want):
    assert listed(vis, status, decided, ref) is want


def test_apply_logs_every_changed_field():
    new, log = apply(None, {"visibility": "approved", "tags_add": ["featured"], "note": " dup? no, real "}, TAGS, 21350)
    assert new == {"visibility": "approved", "tags": ["featured"], "note": "dup? no, real", "decided_ref_cents": 21350}
    assert log == [("visibility", "auto", "approved"), ("tags", "", "featured"), ("note", None, "dup? no, real"),
                   ("decided_ref_cents", None, "21350")]
    new2, log2 = apply(new, {"tags_add": ["newsletter"], "tags_remove": ["featured"]}, TAGS, None)
    assert new2["tags"] == ["newsletter"] and new2["visibility"] == "approved" and new2["decided_ref_cents"] == 21350
    assert log2 == [("tags", "featured", "newsletter")]
    new3, log3 = apply(new2, {"visibility": "hidden"}, TAGS, 30000)
    assert new3["decided_ref_cents"] is None and ("visibility", "approved", "hidden") in log3
    assert apply(new3, {"visibility": "hidden"}, TAGS, None)[1] == []          # no change, no log row


def test_reapproving_renews_the_baseline():
    cur = {"visibility": "approved", "tags": [], "note": None, "decided_ref_cents": 10000}
    new, log = apply(cur, {"visibility": "approved"}, TAGS, 15000)
    assert new["decided_ref_cents"] == 15000 and log == [("decided_ref_cents", "10000", "15000")]


@pytest.mark.parametrize("change", [
    {}, {"visibility": "rejected"}, {"tags_add": ["spam"]}, {"tags_remove": "featured"}, {"note": "x" * 501},
    {"status": "approved"},
])
def test_apply_rejects_bad_changes(change):
    with pytest.raises(ValueError):
        apply(None, change, TAGS, 10000)
