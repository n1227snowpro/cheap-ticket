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
    width: 600px; height: 340px;
    background: #f0f2f5;
    font-family: "Noto Sans CJK TC", "Noto Sans TC", "PingFang TC",
                 "Microsoft JhengHei", -apple-system, BlinkMacSystemFont, sans-serif;
    display: flex; align-items: center; justify-content: center;
  }}
  .card {{
    width: 560px; height: 300px;
    background: #ffffff;
    border-radius: 18px;
    border: 1px solid #e0e4ea;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    padding: 26px 28px 22px;
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}

  /* ── Row 1: airline name + flag badge ── */
  .row-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .airline-name {{
    font-size: 18px;
    font-weight: 700;
    color: #111827;
    letter-spacing: 0.2px;
  }}
  .flag-badge {{
    display: flex;
    align-items: center;
    gap: 6px;
    background: #f3f4f6;
    border: 1px solid #e0e4ea;
    border-radius: 20px;
    padding: 5px 14px 5px 8px;
  }}
  .flag {{ font-size: 22px; line-height: 1; }}
  .flag-label {{
    font-size: 14px;
    color: #374151;
    font-weight: 600;
  }}

  /* ── Row 2: logo + route + dest ── */
  .row-mid {{
    display: flex;
    align-items: center;
    gap: 18px;
    flex: 1;
    padding: 14px 0 8px;
  }}
  .airline-logo {{
    width: 60px;
    height: 60px;
    border-radius: 50%;
    object-fit: contain;
    background: #f9fafb;
    border: 1px solid #e0e4ea;
    flex-shrink: 0;
    padding: 4px;
  }}
  .airline-logo-placeholder {{
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: #f3f4f6;
    border: 1px solid #e0e4ea;
    display: flex; align-items: center; justify-content: center;
    font-size: 26px;
    flex-shrink: 0;
  }}
  .route-block {{
    display: flex;
    flex-direction: column;
    gap: 5px;
  }}
  .route {{
    font-size: 30px;
    font-weight: 800;
    color: #111827;
    letter-spacing: 0.5px;
    line-height: 1;
  }}
  .route-sub {{
    font-size: 13px;
    color: #6b7280;
    letter-spacing: 0.3px;
  }}
  .dest-block {{
    margin-left: auto;
    text-align: right;
  }}
  .dest-zh {{
    font-size: 36px;
    font-weight: 800;
    color: #111827;
    line-height: 1;
  }}
  .dest-tag {{
    font-size: 12px;
    color: #9ca3af;
    margin-top: 4px;
  }}

  /* ── Row 3: date + price ── */
  .row-bottom {{
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    border-top: 1px solid #f0f2f5;
    padding-top: 14px;
  }}
  .date-block {{
    display: flex;
    flex-direction: column;
    gap: 2px;
  }}
  .date-label {{
    font-size: 11px;
    color: #9ca3af;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }}
  .date-val {{
    font-size: 15px;
    color: #374151;
    font-weight: 500;
  }}
  .price-block {{
    text-align: right;
  }}
  .price-prefix {{
    font-size: 16px;
    color: #374151;
    font-weight: 500;
  }}
  .price {{
    font-size: 40px;
    font-weight: 800;
    color: #111827;
    letter-spacing: -1px;
    line-height: 1;
  }}
  .watermark {{
    position: absolute;
    bottom: 10px;
    right: 16px;
    font-size: 10px;
    color: #d1d5db;
    letter-spacing: 0.3px;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="row-top">
    <div class="airline-name">{airline_label}</div>
    <div class="flag-badge">
      <span class="flag">{flag}</span>
      <span class="flag-label">{dest_zh}</span>
    </div>
  </div>

  <div class="row-mid">
    {logo_tag}
    <div class="route-block">
      <div class="route">TPE → {iata}</div>
      <div class="route-sub">{dest_en}</div>
    </div>
    <div class="dest-block">
      <div class="dest-zh">{dest_zh}</div>
      <div class="dest-tag">直飛優先</div>
    </div>
  </div>

  <div class="row-bottom">
    <div class="date-block">
      <div class="date-label">最佳日期</div>
      <div class="date-val">{date_zh}</div>
    </div>
    <div class="price-block">
      <span class="price-prefix">NT$</span>
      <span class="price">{price}</span>
    </div>
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
