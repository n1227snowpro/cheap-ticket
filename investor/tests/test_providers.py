from providers import eodhd, sec_edgar, social


def test_eodhd_normalize():
    raw = {
        "General": {"Code": "ABC", "Name": "ABC Corp", "Sector": "Technology", "Industry": "Software"},
        "Highlights": {"MarketCapitalization": 5e9, "EPSEstimateCurrentYear": "2.0", "EPSEstimateNextYear": "2.4"},
        "AnalystRatings": {"TargetPrice": "55.5", "Rating": "4.1"},
        "SharesStats": {"SharesOutstanding": 1e8},
        "Earnings": {"Trend": {"2026-12-31": {"period": "+1y", "epsTrendCurrent": "2.4", "epsTrend90daysAgo": "2.2"},
                               "2027-12-31": {"period": "+5y", "growth": "0.15"}}},
        "Financials": {
            "Income_Statement": {"yearly": {
                "2024-12-31": {"totalRevenue": "1000", "grossProfit": "600", "operatingIncome": "200", "netIncome": "150", "ebitda": "250"},
                "2023-12-31": {"totalRevenue": "900", "grossProfit": "520", "operatingIncome": "170", "netIncome": "120", "ebitda": None}}},
            "Balance_Sheet": {"yearly": {
                "2024-12-31": {"totalAssets": "3000", "totalStockholderEquity": "1500", "commonStockSharesOutstanding": None, "cash": "200"}}},
            "Cash_Flow": {"yearly": {
                "2024-12-31": {"totalCashFromOperatingActivities": "220", "capitalExpenditures": "-50", "dividendsPaid": "-40"}}},
        },
    }
    s = eodhd.normalize_fundamentals("ABC", raw)
    assert s["name"] == "ABC Corp" and s["sector"] == "Technology"
    assert [y["year"] for y in s["annual"]] == [2023, 2024]
    cur = s["annual"][-1]
    assert cur["revenue"] == 1000 and cur["cash"] == 200 and cur["shares"] == 1e8
    assert s["estimates"]["eps_trend_90d"] == 2.2 and s["estimates"]["eps_growth_5y"] == 0.15
    assert s["analyst"]["target_price"] == 55.5
    assert eodhd._symbol("BRK.B") == "BRK-B.US"


FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>25.5</value></transactionPricePerShare></transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>5</value></transactionShares></transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_parse_form4_keeps_open_market_only():
    out = sec_edgar.parse_form4(FORM4, "ABC", "2026-10-01")
    assert out == [{"ticker": "ABC", "filed_at": "2026-10-01", "owner": "Doe Jane", "title": "CEO",
                    "code": "P", "shares": 1000.0, "price": 25.5, "value": 25500.0}]


def test_extract_tickers():
    uni = {"AAPL", "IT", "NVDA", "ON"}
    assert social.extract_tickers("Loading up on $NVDA and AAPL, IT is ON fire", uni) == {"NVDA", "AAPL"}
    assert social.extract_tickers("$ON earnings tomorrow", uni) == {"ON"}
