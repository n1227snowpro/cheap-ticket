import fixtures
import scoring


def test_percentile():
    peers = [1, 2, 3, 4, 5]
    assert scoring._percentile(5, peers, True) == 1.0
    assert scoring._percentile(1, peers, True) == 0.0
    assert scoring._percentile(1, peers, False) == 1.0


def test_universe_scores_bounded_and_ranked():
    d = fixtures.generate()
    rows = scoring.build_rows(d["stocks"], d["prices"], d["spy"], {})
    assert len(rows) == len(fixtures.PROFILES)
    for r in rows:
        for g in scoring.GROUPS + ("composite",):
            assert r[g] is None or 0 <= r[g] <= 100
        assert r["reasons"]["good"] or r["reasons"]["bad"]
    comps = [r["composite"] for r in rows]
    assert comps == sorted(comps, reverse=True)


def test_loss_maker_scores_low_on_value():
    d = fixtures.generate()
    rows = {r["ticker"]: r for r in scoring.build_rows(d["stocks"], d["prices"], d["spy"], {})}
    # GENX is a loss-making biotech in the fixtures
    assert rows["GENX"]["value"] < 30


def test_presets_and_filters():
    d = fixtures.generate()
    rows = scoring.build_rows(d["stocks"], d["prices"], d["spy"], {})
    for key, p in scoring.PRESETS.items():
        for r in scoring.screen(rows, preset=key):
            assert p["rule"](r["metrics"], r)
    hyper = scoring.screen(rows, preset="hypergrowth")
    assert all(r["metrics"]["rev_cagr_3y"] > 0.25 for r in hyper)
    tech = scoring.screen(rows, sector="Technology", min_scores={"quality": 50})
    assert all(r["sector"] == "Technology" and r["quality"] >= 50 for r in tech)


def test_signal_driven_tags():
    d = fixtures.generate()
    sig = {"CLDX": {"buzz_z": 3.0, "mentions_7d": 500}, "BYTE": {"insider_buyers": 3}}
    rows = {r["ticker"]: r for r in scoring.build_rows(d["stocks"], d["prices"], d["spy"], sig)}
    assert "Buzzing" in rows["CLDX"]["tags"] and "Hype Warning" in rows["CLDX"]["tags"]
    assert "Insiders Buying" in rows["BYTE"]["tags"]
