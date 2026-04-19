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
    region_zh = REGION_ZH.get(row.get("region", ""), row.get("region", ""))
    price = f"{int(row['price']):,}" if row.get("price") else "—"
    currency = row.get("currency", "TWD")
    date_zh = _fmt_date_zh(row.get("best_date", ""))
    airline_name = row.get("airline_name", "") or ""
    airline_logo = _airline_logo_url(airline_name)
    if airline_name:
        hide = "this.style.display='none'"
        logo_tag = f'<img class="airline-logo" src="{airline_logo}" onerror="{hide}" alt="">' if airline_logo else ""
        airline_html = f'<div class="airline-row">{logo_tag}<span class="airline-name">{airline_name}</span></div>'
    else:
        airline_html = ""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  @import url('data:text/css,');
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: 600px; height: 340px;
    background: #0f1117;
    font-family: "Noto Sans CJK TC", "Noto Sans TC", "PingFang TC",
                 "Microsoft JhengHei", -apple-system, BlinkMacSystemFont, sans-serif;
    display: flex; align-items: center; justify-content: center;
  }}
  .card {{
    width: 560px; height: 300px;
    background: #1a1d27;
    border-radius: 20px;
    border: 1px solid #2e3250;
    padding: 28px 32px;
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}
  .top-row {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
  }}
  .flag {{ font-size: 44px; line-height: 1; }}
  .badge {{
    background: #22263a;
    border: 1px solid #2e3250;
    color: #7c83a8;
    font-size: 14px;
    padding: 5px 14px;
    border-radius: 20px;
    letter-spacing: 0.5px;
  }}
  .dest-zh {{
    font-size: 44px;
    font-weight: 700;
    color: #e8eaf6;
    line-height: 1.1;
    margin-top: 6px;
  }}
  .dest-sub {{
    font-size: 15px;
    color: #7c83a8;
    margin-top: 5px;
    letter-spacing: 0.3px;
  }}
  .sep {{ margin: 0 6px; }}
  .price-row {{ display: flex; align-items: baseline; gap: 6px; }}
  .price {{
    font-size: 50px;
    font-weight: 800;
    color: #4ade80;
    line-height: 1;
    letter-spacing: -1px;
  }}
  .currency {{
    font-size: 18px;
    color: #7c83a8;
    font-weight: 400;
  }}
  .date {{
    font-size: 14px;
    color: #7c83a8;
    margin-top: 6px;
  }}
  .airline-row {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 10px;
  }}
  .airline-logo {{
    width: 24px;
    height: 24px;
    border-radius: 4px;
    object-fit: contain;
    background: #22263a;
  }}
  .airline-name {{
    font-size: 13px;
    color: #7c83a8;
  }}
  .watermark {{
    position: absolute;
    bottom: 14px;
    right: 20px;
    font-size: 11px;
    color: #2e3250;
    letter-spacing: 0.3px;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="top-row">
    <div class="flag">{flag}</div>
    <div class="badge">{region_zh}</div>
  </div>
  <div>
    <div class="dest-zh">{dest_zh}</div>
    <div class="dest-sub">{dest_en}<span class="sep">·</span>TPE → {iata}</div>
  </div>
  <div>
    <div class="price-row">
      <div class="price">{price}</div>
      <div class="currency">{currency}</div>
    </div>
    <div class="date">最佳日期：{date_zh}</div>
    {airline_html}
  </div>
  <div class="watermark">flights.srv1213330.hstgr.cloud</div>
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
        page = browser.new_page(viewport={"width": 600, "height": 340})
        page.set_content(html, wait_until="networkidle")
        page.screenshot(
            path=str(out_path),
            clip={"x": 0, "y": 0, "width": 600, "height": 340},
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
