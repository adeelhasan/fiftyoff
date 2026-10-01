import json

import pytest

import preflight
from fiftyoff.keepa import BudgetExceeded, FixtureTransport, Keepa, Ledger
from tests.fixtures import build


@pytest.fixture
def env(tmp_path):
    fx = tmp_path / "fx"
    build.write(fx)
    root = tmp_path / "research"
    return fx, root


def run(fx, root, *args, answers=()):
    it = iter(answers)
    return preflight.main(["--fixtures", str(fx), "--root", str(root), *args], input_fn=lambda _: next(it))


def test_dry_run_makes_no_calls(env, monkeypatch):
    fx, root = env
    monkeypatch.setattr(FixtureTransport, "request", lambda *a: pytest.fail("called Keepa"))
    assert run(fx, root, "census", "--dry-run") == 0
    assert not (root / "token-ledger.jsonl").exists()


def test_declining_confirmation_spends_nothing(env):
    fx, root = env
    assert run(fx, root, "census", answers=["n"]) == 1
    # only the free probe is on the ledger
    entries = Ledger(root / "token-ledger.jsonl").entries()
    assert [e["label"] for e in entries] == ["probe"]


def test_end_to_end_on_fixtures(env):
    fx, root = env
    assert run(fx, root, "census", answers=["y"]) == 0
    assert run(fx, root, "propose") == 0
    cand = json.loads((root / "candidates.json").read_text())
    # best strict discount first; $50/$30 references are under the $100 floor; the red variant shares a parent
    assert [c["asin"] for c in cand["candidates"]] == ["B0TOOLS001", "B0KITCHEN1", "B0FITNESS1", "B0ELEC0001"]

    assert run(fx, root, "history") == 1  # not approved yet
    cand["approved"] = True
    (root / "candidates.json").write_text(json.dumps(cand))
    assert run(fx, root, "history", answers=["y"]) == 0
    assert run(fx, root, "report") == 0

    md = (root / "preflight-report.md").read_text()
    assert ": GO**" in md and "Observation density" in md
    raw = list((root / "raw").rglob("*.json"))
    assert raw and all("key" not in json.loads(f.read_text())["request"]["params"] for f in raw)


def test_budget_cap_refuses_before_calling(tmp_path):
    fx = tmp_path / "fx"
    build.write(fx)
    k = Keepa(FixtureTransport(fx), Ledger(tmp_path / "l.jsonl"), tmp_path / "raw", token_cap=4)
    with pytest.raises(BudgetExceeded):
        k.call("deal", label="deal-p0", estimate=5, body={"page": 0})
    assert k.transport.calls == []


def test_raw_is_written_before_errors_surface(tmp_path):
    class Failing:
        def request(self, *a):
            return 429, {"tokensLeft": -3, "tokensConsumed": 0, "error": {"message": "out of tokens"}}

    k = Keepa(Failing(), Ledger(tmp_path / "l.jsonl"), tmp_path / "raw", token_cap=100)
    with pytest.raises(Exception):
        k.call("deal", label="deal-p0", estimate=5, body={"page": 0})
    assert len(list((tmp_path / "raw").glob("*.json"))) == 1
    assert Ledger(tmp_path / "l.jsonl").entries()[0]["status"] == 429


def test_failing_probe_does_not_block_census(env, monkeypatch):
    fx, root = env
    real = FixtureTransport.request

    def request(self, endpoint, params, body):
        if params.get("update") == -1:
            return 400, {"tokensLeft": 900, "refillRate": 20, "tokensConsumed": 0,
                         "error": {"message": "invalid asin"}}
        return real(self, endpoint, params, body)

    monkeypatch.setattr(FixtureTransport, "request", request)
    assert run(fx, root, "census", answers=["y"]) == 0


def test_census_runs_counts_once_and_samples_until_short_page(env):
    fx, root = env
    assert run(fx, root, "census", answers=["y"]) == 0
    labels = [e["label"] for e in Ledger(root / "token-ledger.jsonl").entries()]
    assert labels.count("smp-pool50-p0") == 1 and "smp-pool50-p1" not in labels  # 7 rows < 150
    assert all(l.endswith("-p0") for l in labels if l.startswith("cnt-"))


def test_census_refuses_plans_over_max_pages(env, tmp_path):
    fx, root = env
    cfg = tmp_path / "cfg.toml"
    cfg.write_text(open("preflight.toml").read().replace("max_pages = 40", "max_pages = 3"))
    assert preflight.main(["--config", str(cfg), "--fixtures", str(fx), "--root", str(root), "census"],
                          input_fn=lambda _: pytest.fail("should not ask")) == 1
