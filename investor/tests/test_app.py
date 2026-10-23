import pytest


@pytest.fixture(scope="module")
def client():
    import app as app_module
    return app_module.app.test_client()


def test_pages_render(client):
    for path in ("/", "/screener", "/stock/NOVA", "/feed", "/watchlist", "/learn"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert b"not financial advice" in r.data


def test_today(client):
    d = client.get("/api/today").get_json()
    assert d["status"]["demo"] is True
    assert d["top_value"] and d["top_growth"] and d["benchmark"]
    assert {"ticker", "value", "growth", "quality", "momentum", "reasons", "m"} <= set(d["top_value"][0])


def test_screen_and_sort(client):
    d = client.get("/api/screen?preset=dividend&sort=dividend_yield&dir=desc").get_json()
    ys = [r["m"]["dividend_yield"] for r in d["results"]]
    assert d["total"] == len(ys) > 0 and ys == sorted(ys, reverse=True)
    assert client.get("/api/screen?min_quality=99").get_json()["total"] == 0


def test_stock_detail(client):
    d = client.get("/api/stock/byte").get_json()
    assert d["ticker"] == "BYTE" and d["checks"] and d["prices"] and d["news"]
    assert client.get("/api/stock/NOPE").status_code == 404


def test_feed_and_refresh(client):
    items = client.get("/api/feed?mood=negative").get_json()["items"]
    assert items and all(i["sentiment"] < -0.1 for i in items)
    assert client.post("/api/refresh?job=prices").status_code == 400  # jobs disabled in demo mode
