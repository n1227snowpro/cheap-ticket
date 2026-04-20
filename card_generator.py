"""
Generates a social-media card image for a flight result using Playwright.
The card matches the app's dark theme and includes flag, destination name (ZH),
price, and best date. Images are auto-deleted after 1 hour.
"""

import os
import threading
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

DATA_DIR = Path(os.environ.get(
    "CHEAPTICKET_DATA",
    str(Path.home() / "Library" / "Application Support" / "CheapTicket")
))
CARDS_DIR = DATA_DIR / "cards"

# Maps common airline display names → IATA codes (for logo service)
AIRLINE_IATA = {
    "China Airlines": "CI", "EVA Air": "BR", "Starlux Airlines": "JX", "Starlux": "JX",
    "AirAsia": "AK", "AirAsia X": "D7", "Thai Airways": "TG", "Thai Lion Air": "SL",
    "Singapore Airlines": "SQ", "Scoot": "TR", "Cathay Pacific": "CX",
    "Hong Kong Express": "UO", "HK Express": "UO",
    "Korean Air": "KE", "Asiana Airlines": "OZ", "Asiana": "OZ",
    "Japan Airlines": "JL", "All Nippon Airways": "NH", "ANA": "NH",
    "Peach": "MM", "Peach Aviation": "MM", "Jetstar": "JQ",
    "Jetstar Japan": "GK", "Jetstar Asia": "3K",
    "Vietnam Airlines": "VN", "VietJet Air": "VJ", "VietJet": "VJ",
    "Bamboo Airways": "QH", "Philippine Airlines": "PR", "Cebu Pacific": "5J",
    "Air France": "AF", "British Airways": "BA", "Lufthansa": "LH",
    "United Airlines": "UA", "American Airlines": "AA", "Delta Air Lines": "DL",
    "Qantas": "QF", "Garuda Indonesia": "GA", "Malaysia Airlines": "MH",
    "Air Macau": "NX", "China Eastern": "MU", "China Southern": "CZ",
    "Tigerair Taiwan": "IT", "TransAsia": "GE",
}


def _airline_logo_url(airline_name: str) -> str:
    """Return a logo URL for the airline, or empty string if unknown."""
    if not airline_name:
        return ""
    # Exact match first, then partial
    code = AIRLINE_IATA.get(airline_name)
    if not code:
        for name, iata in AIRLINE_IATA.items():
            if name.lower() in airline_name.lower() or airline_name.lower() in name.lower():
                code = iata
                break
    if code:
        return f"https://pics.avs.io/100/100/{code}.png"
    return ""


DEST_ZH = {
    "NRT": "東京", "KIX": "大阪", "CTS": "札幌", "FUK": "福岡", "OKA": "沖繩",
    "ICN": "首爾",
    "HKG": "香港", "MFM": "澳門",
    "BKK": "曼谷", "HKT": "普吉島",
    "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港",
    "SIN": "新加坡", "DPS": "峇里島", "MNL": "馬尼拉", "CEB": "宿霧", "KUL": "吉隆坡",
    "CDG": "巴黎", "LHR": "倫敦", "LAX": "洛杉磯", "SYD": "雪梨",
    "GUM": "關島",
}

REGION_ZH = {
    "Japan": "日本", "Korea": "韓國", "HK": "香港", "Macau": "澳門",
    "Thailand": "泰國", "Vietnam": "越南", "SE Asia": "東南亞",
    "Europe": "歐洲", "Americas": "美洲", "Australia": "澳洲", "Pacific": "太平洋",
}


def _fmt_date_zh(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.year}年{d.month}月{d.day}日"
    except Exception:
        return date_str


def _card_html(row: dict) -> str:
    iata = row["iata"]
    flag = row.get("flag", "✈")
    dest_zh = DEST_ZH.get(iata, row["destination"])
    dest_en = row["destination"]
    price = f"{int(row['price']):,}" if row.get("price") else "—"
    currency = row.get("currency", "TWD")
    date_zh = _fmt_date_zh(row.get("best_date", ""))
    airline_name = row.get("airline_name", "") or ""
    airline_logo = _airline_logo_url(airline_name)

    hide = "this.style.display='none'"
    logo_tag = (
        f'<img class="airline-logo" src="{airline_logo}" onerror="{hide}" alt="">'
        if airline_logo else
        '<div class="airline-logo-placeholder">✈</div>'
    )
    airline_label = airline_name if airline_name else "—"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: 600px; height: 300px;
    background: #1c2340;
    font-family: "Noto Sans CJK TC", "Noto Sans TC", "PingFang TC",
                 "Microsoft JhengHei", -apple-system, BlinkMacSystemFont, sans-serif;
  }}
  .card {{
    width: 600px; height: 300px;
    background: #1c2340;
    padding: 28px 32px 24px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}

  /* ── Row 1: airline name ── */
  .airline-name {{
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.3px;
  }}

  /* ── Row 2: logo + route info + right block ── */
  .row-mid {{
    display: flex;
    align-items: center;
    gap: 16px;
    flex: 1;
    padding: 18px 0 10px;
  }}
  .airline-logo {{
    width: 56px;
    height: 56px;
    border-radius: 12px;
    object-fit: contain;
    background: #ffffff;
    flex-shrink: 0;
    padding: 4px;
  }}
  .airline-logo-placeholder {{
    width: 56px;
    height: 56px;
    border-radius: 12px;
    background: #2d3561;
    display: flex; align-items: center; justify-content: center;
    font-size: 26px;
    flex-shrink: 0;
  }}
  .route-block {{
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}
  .route {{
    font-size: 34px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: 0.5px;
    line-height: 1;
  }}
  .route-sub {{
    font-size: 14px;
    color: #8892b0;
    letter-spacing: 0.3px;
  }}
  .right-block {{
    margin-left: auto;
    text-align: right;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}
  .direct {{
    font-size: 18px;
    font-weight: 600;
    color: #ffffff;
  }}
  .dest-sub {{
    font-size: 14px;
    color: #8892b0;
  }}

  /* ── Row 3: date left, price right ── */
  .row-bottom {{
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
  }}
  .date-val {{
    font-size: 14px;
    color: #8892b0;
  }}
  .price-block {{
    text-align: right;
  }}
  .price {{
    font-size: 42px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -1px;
    line-height: 1;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="airline-name">{airline_label}</div>

  <div class="row-mid">
    {logo_tag}
    <div class="route-block">
      <div class="route">TPE → {iata}</div>
      <div class="route-sub">{dest_en}</div>
    </div>
    <div class="right-block">
      <div class="direct">{dest_zh} {flag}</div>
      <div class="dest-sub">最佳日期：{date_zh}</div>
    </div>
  </div>

  <div class="row-bottom">
    <div class="date-val">直飛優先</div>
    <div class="price-block">
      <span class="price">NT${price}</span>
    </div>
  </div>
</div>
</body>
</html>"""


def generate_card(row: dict) -> Path:
    """
    Renders a flight card PNG via Playwright and schedules deletion after 1 hour.
    Returns the path to the generated PNG file.
    """
    CARDS_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"{row['iata']}_{int(time.time())}.png"
    out_path = CARDS_DIR / filename

    html = _card_html(row)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 600, "height": 300})
        page.set_content(html, wait_until="networkidle")
        page.screenshot(
            path=str(out_path),
            clip={"x": 0, "y": 0, "width": 600, "height": 300},
        )
        browser.close()

    # Auto-delete after 1 hour
    def _delete():
        try:
            out_path.unlink()
        except FileNotFoundError:
            pass

    threading.Timer(3600, _delete).start()

    return out_path
