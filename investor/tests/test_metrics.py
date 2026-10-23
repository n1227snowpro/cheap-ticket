import math

import pytest

import metrics as M


def year(**kw):
    base = dict(revenue=1000, gross_profit=400, operating_income=150, net_income=100, ebitda=200,
                total_assets=2000, current_assets=600, current_liabilities=300, total_liabilities=1000,
                long_term_debt=400, short_term_debt=0, equity=1000, retained_earnings=500, cash=100,
                operating_cash_flow=140, capex=-40, dividends_paid=-30, shares=100, rnd=0)
    base.update(kw)
    return base


def test_cagr():
    assert M.cagr(100, 121, 2) == pytest.approx(0.10)
    assert M.cagr(-5, 10, 2) is None
    assert M.cagr(100, 50, 0) is None


def test_graham_number():
    # sqrt(22.5 * 2 * 20) = 30
    assert M.graham_number(2, 20) == pytest.approx(30)
    assert M.graham_number(-1, 20) is None


def test_dcf_zero_growth_is_perpetuity_like():
    # With growth == terminal, value ≈ fcf*(1+g)/(r-g)
    v = M.dcf_per_share(10, 0.03, discount=0.10, terminal=0.03)
    assert v == pytest.approx(10 * 1.03 / 0.07, rel=1e-6)
    assert M.dcf_per_share(-1, 0.1) is None


def test_dcf_caps_growth():
    assert M.dcf_per_share(10, 0.9) == pytest.approx(M.dcf_per_share(10, 0.15))


def test_altman_z_hand_computed():
    y = year()
    z = M.altman_z(y, market_cap=3000)
    expected = 1.2 * 300 / 2000 + 1.4 * 500 / 2000 + 3.3 * 150 / 2000 + 0.6 * 3000 / 1000 + 1.0 * 1000 / 2000
    assert z == pytest.approx(expected)


def test_piotroski_perfect_and_poor():
    prev = year()
    good = year(net_income=150, operating_cash_flow=250, long_term_debt=300, current_assets=700,
                gross_profit=450, revenue=1100, shares=99)
    score, tests = M.piotroski(good, prev)
    assert score == 9 and all(tests.values())
    bad = year(net_income=-50, operating_cash_flow=-100, long_term_debt=600, current_assets=500,
               gross_profit=300, revenue=900, shares=120)
    assert M.piotroski(bad, prev)[0] == 0


def test_analyze_core_ratios():
    s = {"ticker": "T", "price": 20.0,
         "annual": [year(year=2021, revenue=800, net_income=70, shares=100),
                    year(year=2022, revenue=900), year(year=2023, revenue=950), year(year=2024)]}
    m = M.analyze(s)
    assert m["eps"] == pytest.approx(1.0)
    assert m["pe"] == pytest.approx(20.0)
    assert m["pb"] == pytest.approx(2.0)
    assert m["rev_cagr_3y"] == pytest.approx((1000 / 800) ** (1 / 3) - 1)
    assert m["dividend_yield"] == pytest.approx(30 / 2000)
    assert m["debt_equity"] == pytest.approx(0.4)
    assert m["fcf"] == 100


def test_negative_earnings_flagged_not_hidden():
    s = {"ticker": "L", "price": 10.0, "annual": [year(net_income=-50), year(net_income=-20)]}
    m = M.analyze(s)
    assert m["pe"] is None and "pe" in m["_negative"]
    pe_check = next(c for c in M.checklist(m) if c["key"] == "pe")
    assert pe_check["pass"] is False and "losing money" in pe_check["why"]


def test_momentum_from_prices():
    prices = [[f"d{i}", 100 + i] for i in range(300)]
    m = M.analyze({"ticker": "P", "annual": [year()]}, prices=prices,
                  spy_prices=[[f"d{i}", 100] for i in range(300)])
    assert m["price"] == 399
    assert m["above_sma200"] is True
    assert m["pos_52w"] == pytest.approx(1.0)
    assert m["rs_12m"] == pytest.approx(399 / 147 - 1)
