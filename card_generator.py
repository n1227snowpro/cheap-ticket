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

AIRLINE_ZH = {
    "China Airlines": "中華航空", "EVA Air": "長榮航空",
    "Starlux Airlines": "星宇航空", "Starlux": "星宇航空",
    "AirAsia": "亞洲航空", "AirAsia X": "亞洲航空 X",
    "Thai Airways": "泰國航空", "Thai Lion Air": "泰獅航空",
    "Singapore Airlines": "新加坡航空", "Scoot": "酷航",
    "Cathay Pacific": "國泰航空",
    "Hong Kong Express": "香港快運", "HK Express": "香港快運",
    "Korean Air": "大韓航空", "Asiana Airlines": "韓亞航空", "Asiana": "韓亞航空",
    "Japan Airlines": "日本航空", "All Nippon Airways": "全日空", "ANA": "全日空",
    "Peach": "樂桃航空", "Peach Aviation": "樂桃航空",
    "Jetstar": "捷星航空", "Jetstar Japan": "捷星日本", "Jetstar Asia": "捷星亞洲",
    "Vietnam Airlines": "越南航空", "VietJet Air": "越捷航空", "VietJet": "越捷航空",
    "Bamboo Airways": "竹子航空", "Philippine Airlines": "菲律賓航空",
    "Cebu Pacific": "宿霧太平洋航空",
    "Air France": "法國航空", "British Airways": "英國航空", "Lufthansa": "漢莎航空",
    "United Airlines": "聯合航空", "American Airlines": "美國航空",
    "Delta Air Lines": "達美航空", "Qantas": "澳洲航空",
    "Garuda Indonesia": "印尼鷹航", "Malaysia Airlines": "馬來西亞航空",
    "Air Macau": "澳門航空", "China Eastern": "中國東方航空",
    "China Southern": "中國南方航空", "Tigerair Taiwan": "台灣虎航",
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
    duration = row.get("duration", "") or ""
    airline_name = row.get("airline_name", "") or ""
    airline_logo = _airline_logo_url(airline_name)
    # Chinese airline name — exact match first, then partial
    airline_zh = AIRLINE_ZH.get(airline_name, "")
    if not airline_zh:
        for en, zh in AIRLINE_ZH.items():
            if en.lower() in airline_name.lower() or airline_name.lower() in en.lower():
                airline_zh = zh
                break
    airline_label = airline_zh if airline_zh else airline_name if airline_name else "—"

    hide = "this.style.display='none'"
    logo_tag = (
        f'<img class="airline-logo" src="{airline_logo}" onerror="{hide}" alt="">'
        if airline_logo else
        '<div class="airline-logo-placeholder">✈</div>'
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: 600px; height: 300px;
    background: #ffffff;
    font-family: "Noto Sans CJK TC", "Noto Sans TC", "PingFang TC",
                 "Microsoft JhengHei", -apple-system, BlinkMacSystemFont, sans-serif;
  }}
  .card {{
    width: 600px; height: 300px;
    background: #ffffff;
    padding: 26px 30px 24px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}

  /* ── Row 1: airline name + icons ── */
  .row-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .airline-name {{
    font-size: 28px;
    font-weight: 800;
    color: #111827;
    letter-spacing: -0.3px;
  }}
  .icons {{
    display: flex;
    gap: 22px;
    align-items: center;
  }}
  .icon {{
    width: 34px; height: 34px;
    color: #111827;
    flex-shrink: 0;
    stroke-width: 1.8;
  }}

  /* ── Row 2: logo + time/route + right ── */
  .row-mid {{
    display: flex;
    align-items: center;
    gap: 16px;
    flex: 1;
    padding: 16px 0 10px;
  }}
  .airline-logo {{
    width: 52px;
    height: 52px;
    border-radius: 10px;
    object-fit: contain;
    background: #f3f4f6;
    flex-shrink: 0;
    padding: 3px;
    border: 1px solid #e5e7eb;
  }}
  .airline-logo-placeholder {{
    width: 52px;
    height: 52px;
    border-radius: 10px;
    background: #f3f4f6;
    border: 1px solid #e5e7eb;
    display: flex; align-items: center; justify-content: center;
    font-size: 24px;
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
    letter-spacing: 0.3px;
    line-height: 1;
  }}
  .route-sub {{
    font-size: 13px;
    color: #6b7280;
  }}
  .right-block {{
    margin-left: auto;
    text-align: right;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }}
  .direct {{
    font-size: 28px;
    font-weight: 800;
    color: #111827;
    letter-spacing: -0.3px;
  }}
  .dest-date {{
    font-size: 20px;
    font-weight: 600;
    color: #374151;
  }}

  /* ── Row 3: price ── */
  .row-bottom {{
    display: flex;
    align-items: flex-end;
    justify-content: flex-end;
  }}
  .price {{
    font-size: 40px;
    font-weight: 800;
    color: #111827;
    letter-spacing: -1px;
    line-height: 1;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="row-top">
    <div class="airline-name">{airline_label}</div>
    <div class="icons">
      <!-- Share icon -->
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>
        <polyline points="16 6 12 2 8 6"/>
        <line x1="12" y1="2" x2="12" y2="15"/>
      </svg>
      <!-- Heart icon -->
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
      </svg>
    </div>
  </div>

  <div class="row-mid">
    {logo_tag}
    <div class="route-block">
      <div class="route">TPE → {iata}</div>
      <div class="route-sub">{dest_en}</div>
    </div>
    <div class="right-block">
      <div class="direct">直飛</div>
      {'<div class="dest-date">' + duration + '</div>' if duration else ''}
    </div>
  </div>

  <div class="row-bottom">
    <div class="price">NT${price}</div>
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
