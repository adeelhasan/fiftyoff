"""The API rater (fiftyoff/rater.py) on a fake store and a fake model call: no database, no network."""

import subprocess
import sys
from datetime import datetime, timezone

from fiftyoff import rater
from fiftyoff.api import APPEAL_MODEL

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
CFG = rater.RaterConfig(batch=2, max_batches=3, monthly_usd_cap=1.0)
GOOD = {"B0RATE0001": "B0RATE0001\t8\ttravel\tluggage\thardside luggage\tn\t-\tCoveted brand",
        "B0RATE0002": "B0RATE0002\t2\tdiy\ttools-ladders\tjig\tn\t-\tNiche trade jig",
        "B0RATE0003": "B0RATE0003\t5\tkitchen\tcookware-knives\tsantoku knives\tn\t-\tGood knife"}


class FakeStore:
    def __init__(self, keys, spent=0.0, rated=()):
        self.queue = [[k, f"Title {k}", "Brand", "Cat > Sub"] for k in keys]
        self.saved, self.batches, self.spent, self.rated = [], [], spent, list(rated)

    def candidates(self, limit):
        done = {r[0] for r in self.saved}
        return [r for r in self.queue if r[0] not in done][:limit]

    def rated_sample(self, limit, rated_by):
        return self.rated[:limit]

    def save(self, rows, prompt_v):
        self.saved += rows
        return len(rows)

    def record(self, b):
        self.batches.append(b)
        self.spent += b["usd"]

    def spent_since(self, since):
        return self.spent


def fake_call(lines=GOOD, stop="end_turn", calls=None):
    def call(system, user, cfg):
        if calls is not None:
            calls.append(user)
        keys = [ln.split("\t")[0] for ln in user.splitlines() if ln.startswith("B0")]
        return rater.Reply(text="\n".join(lines[k] for k in keys if k in lines), stop_reason=stop, request_id="req_1",
                           input_tokens=1000, output_tokens=200, cache_read_tokens=2600)
    return call


def test_rates_until_nothing_is_left_and_stores_ratings_where_the_feed_reads_them():
    s = FakeStore(GOOD)
    calls = []
    sent = rater.round_(s, fake_call(calls=calls), CFG, log=lambda m: None, clock=lambda: NOW)
    assert sent == 3 and len(calls) == 2 and {r[0] for r in s.saved} == set(GOOD)
    assert rater.MODEL == APPEAL_MODEL and rater.RATED_BY == "api"  # else the shelves never see these ratings
    b = s.batches[0]
    assert (b["model_id"], b["loaded"], b["bad"], b["cache_read_tokens"]) == ("claude-sonnet-5-5", 2, 0, 2600)
    assert b["usd"] == round((1000 * 2 + 200 * 10 + 2600 * 0.2) / 1e6, 4)


def test_bad_or_missing_lines_and_unasked_keys_are_not_loaded():
    lines = {**GOOD, "B0RATE0002": "B0RATE0002\t2\tdiy\tdiy\ttools-ladders\tjig\tn\t-\tdoubled aisle column"}
    s = FakeStore(["B0RATE0001", "B0RATE0002"])
    rater.batch(s, fake_call(lines), CFG, NOW, log=lambda m: None)
    assert [r[0] for r in s.saved] == ["B0RATE0001"] and s.batches[0]["bad"] == 1


def test_a_cut_off_reply_loads_nothing_and_is_recorded():
    s = FakeStore(["B0RATE0001"])
    rater.batch(s, fake_call(stop="max_tokens"), CFG, NOW, log=lambda m: None)
    assert s.saved == [] and s.batches[0]["error"] == "stop_reason max_tokens" and s.batches[0]["usd"] > 0


def test_an_api_error_is_recorded_and_the_loop_survives():
    def boom(system, user, cfg):
        raise RuntimeError("overloaded")
    s = FakeStore(["B0RATE0001"])
    rater.batch(s, boom, CFG, NOW, log=lambda m: None)
    assert s.saved == [] and s.batches[0]["error"].startswith("RuntimeError")


def test_no_call_once_the_monthly_cap_is_reached_or_on_a_dry_run():
    calls = []
    s = FakeStore(GOOD, spent=1.0)
    assert rater.round_(s, fake_call(calls=calls), CFG, log=lambda m: None, clock=lambda: NOW) == 0
    s = FakeStore(GOOD)
    rater.round_(s, fake_call(calls=calls), CFG, log=lambda m: None, dry=True, clock=lambda: NOW)
    assert calls == [] and s.batches == [] and s.saved == []


def test_compare_reports_agreement_and_saves_nothing():
    rated = [["B0RATE0001", "t", "b", "c", 7, "luggage"],    # same band (7+), same shelf
             ["B0RATE0002", "t", "b", "c", 4, "tools-ladders"],  # 4 -> 2: band differs
             ["B0RATE0003", "t", "b", "c", 5, "cookware-knives"]]
    s = FakeStore([], rated=rated)
    out = rater.compare(s, fake_call(), CFG, NOW, n=3, log=lambda m: None)
    assert (out["compared"], out["band_agree"], out["score_exact"], out["shelf_agree"]) == (3, 2, 1, 3)
    assert s.saved == [] and len(s.batches) == 2 and all(b["loaded"] == 0 for b in s.batches)


def test_the_tracker_never_imports_a_model_client():
    """Rule 7: same image, so check the import graph rather than trust it."""
    code = "import sys, fiftyoff.tracker, fiftyoff.rater; print('anthropic' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_the_client_caches_the_rubric_sets_effort_and_reads_usage():
    from types import SimpleNamespace as NS

    from fiftyoff.claude_client import make_call
    sent = {}

    class Messages:
        def create(self, **kw):
            sent.update(kw)
            return NS(content=[NS(type="thinking", thinking=""), NS(type="text", text="B0RATE0001\t8")],
                      stop_reason="end_turn", _request_id="req_9",
                      usage=NS(input_tokens=900, output_tokens=150, cache_read_input_tokens=2600,
                               cache_creation_input_tokens=None))

    r = make_call(NS(messages=Messages()))("RUBRIC", "PRODUCTS", rater.RaterConfig(effort="medium"))
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"} and sent["output_config"] == {"effort": "medium"}
    assert sent["model"] == "claude-sonnet-5-5" and "thinking" not in sent
    assert (r.text, r.request_id, r.cache_read_tokens, r.cache_write_tokens) == ("B0RATE0001\t8", "req_9", 2600, 0)
