"""
Direct Playwright scraper for trip.com flight prices.

trip.com serves prices in USD in headless contexts regardless of locale.
We fetch the live USD→TWD exchange rate once per scan and convert.

Strategy per destination:
  - 2 page loads (today+21 and today+56 days)
  - Wait for [class*="FlightItem"] cards then extract US$ prices
  - Convert to TWD using live exchange rate
  - Booking URLs link to trip.com with affiliate params

Confirmed selectors (live DOM inspection Apr 2026):
  - Flight cards:  [class*="FlightItem"]  (class="result-item J_FlightItem …")
  - Prices in cards: match /US\$\s*([\d,]+)/ or /TWD\s*([\d,]+)/
"""

import logging
import random
import re
import time
from datetime import date, timedelta

import requests

import config

logger = logging.getLogger(__name__)

DATE_OFFSETS = [21, 56]       # 3 weeks and 8 weeks out
USD_TWD_RATE = None           # cached exchange rate per scan


def _get_usd_twd_rate() -> float:
    """Fetch live USD→TWD exchange rate. Falls back to 32.5 if API fails."""
    global USD_TWD_RATE
    if USD_TWD_RATE:
        return USD_TWD_RATE
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=8)
        data = r.json()
        rate = data["rates"]["TWD"]
        USD_TWD_RATE = float(rate)
        logger.info(f"Exchange rate: 1 USD = {USD_TWD_RATE:.2f} TWD")
        return USD_TWD_RATE
    except Exception as e:
        logger.warning(f"Exchange rate fetch failed: {e} — using 32.5")
        return 32.5


def reset_rate_cache():
    """Call at start of each scan so the rate is refreshed daily."""
    global USD_TWD_RATE
    USD_TWD_RATE = None


def _trip_book_url(slug: str, iata: str, depdate: str) -> str:
    affiliate = config.trip_affiliate_params()
    return (
        f"https://www.trip.com/flights/{slug}/tickets-TPE-{iata}-economy-class/"
        f"?depdate={depdate}&cabin=Y&qty=1&SortType=Price&{affiliate}"
    )


def _parse_price(text: str):
    """
    Extract numeric price from flight card text.
    Handles: TWD 5,440  |  US$171  |  USD 171
    Returns (value, currency_str).
    """
    m = re.search(r'TWD\s*([\d,]+)', text)
    if m:
        return float(m.group(1).replace(',', '')), 'TWD'
    m = re.search(r'US\$\s*([\d,]+)', text)
    if m:
        return float(m.group(1).replace(',', '')), 'USD'
    m = re.search(r'USD\s*([\d,]+)', text)
    if m:
        return float(m.group(1).replace(',', '')), 'USD'
    return None, None


def scrape_destination(dest: dict) -> dict:
    """
    Returns dict: {iata, price, currency, best_date, booking_url, status, error_msg}
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return {
            "iata": dest["iata"],
            "status": "error",
            "error_msg": "playwright not installed — run: pip install playwright && playwright install chromium",
        }

    iata = dest["iata"]
    slug = dest["slug"]
    best_price_twd = None
    best_date_str = None
    best_airline = None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )

            for offset in DATE_OFFSETS:
                dep_date = (date.today() + timedelta(days=offset)).strftime("%Y-%m-%d")
                url = (
                    f"https://www.trip.com/flights/{slug}/tickets-TPE-{iata}-economy-class/"
                    f"?depdate={dep_date}&cabin=Y&qty=1"
                )
                logger.info(f"[{iata}] {dep_date}: {url}")

                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)

                    # Wait until at least one flight card has a price number
                    try:
                        page.wait_for_function(
                            """() => {
                                const items = document.querySelectorAll('[class*="FlightItem"]');
                                return Array.from(items).some(el => /[\\d,]{3,}/.test(el.innerText));
                            }""",
                            timeout=25000,
                        )
                    except PWTimeout:
                        logger.warning(f"[{iata}] Prices didn't load for {dep_date}")
                        page.close()
                        continue

                    page.wait_for_timeout(1000)

                    # Check for block/captcha
                    if any(k in page.url for k in ("captcha", "security", "blocked")):
                        page.close()
                        return {"iata": iata, "status": "blocked",
                                "error_msg": "trip.com rate limited"}

                    # Extract prices + airline names from all flight cards
                    raw_prices = page.evaluate("""
                        () => {
                            const items = document.querySelectorAll('[class*="FlightItem"]');
                            const out = [];
                            items.forEach(el => {
                                const txt = el.innerText || '';
                                let val = null, curr = null;
                                let m = txt.match(/TWD\\s*([\\d,]+)/);
                                if (m) { val = m[1]; curr = 'TWD'; }
                                else {
                                    m = txt.match(/US\\$\\s*([\\d,]+)/);
                                    if (m) { val = m[1]; curr = 'USD'; }
                                    else {
                                        m = txt.match(/USD\\s*([\\d,]+)/);
                                        if (m) { val = m[1]; curr = 'USD'; }
                                    }
                                }
                                if (!val) return;

                                // Airline name: first non-empty line that isn't a badge/label
                                const SKIP = new Set([
                                    'cheapest','cheapest nonstop','cheapest direct',
                                    'best','fastest','recommended','nonstop','direct',
                                    'stop','1 stop','2 stops','book','sold out','ow','rt',
                                ]);
                                const lines = txt.split('\\n')
                                    .map(s => s.trim())
                                    .filter(s => {
                                        if (s.length < 2) return false;
                                        if (/^[\\d:→\\-\\+]/.test(s)) return false;
                                        const sl = s.toLowerCase();
                                        if (SKIP.has(sl)) return false;
                                        if (sl.startsWith('cheapest')) return false;
                                        if (/^\\d+h/.test(sl)) return false; // duration like "2h 30m"
                                        return true;
                                    });
                                const airline = lines[0] || '';

                                out.push({val, curr, airline});
                            });
                            return out;
                        }
                    """)

                    if not raw_prices:
                        logger.warning(f"[{iata}] No prices extracted for {dep_date}")
                        page.close()
                        continue

                    # Convert everything to TWD and find cheapest
                    rate = _get_usd_twd_rate()
                    converted = []
                    for p in raw_prices:
                        val = float(p["val"].replace(",", ""))
                        twd = round(val * rate) if p["curr"] == "USD" else round(val)
                        converted.append((twd, p.get("airline", "")))

                    converted.sort(key=lambda x: x[0])
                    cheapest, cheapest_airline = converted[0]
                    logger.info(
                        f"[{iata}] {dep_date}: TWD {cheapest:,} "
                        f"({cheapest_airline}, {len(raw_prices)} flights)"
                    )

                    if best_price_twd is None or cheapest < best_price_twd:
                        best_price_twd = cheapest
                        best_date_str = dep_date
                        best_airline = cheapest_airline

                except Exception as e:
                    logger.warning(f"[{iata}] Error on {dep_date}: {e}")
                finally:
                    page.close()

                if offset != DATE_OFFSETS[-1]:
                    time.sleep(random.uniform(2.0, 4.5))

            browser.close()

    except Exception as e:
        logger.error(f"[{iata}] Playwright error: {e}", exc_info=True)
        return {"iata": iata, "status": "error", "error_msg": str(e)[:200]}

    if best_price_twd is None:
        return {"iata": iata, "status": "no_data",
                "error_msg": "No flight prices found on trip.com"}

    booking_url = _trip_book_url(slug, iata, best_date_str)
    logger.info(f"[{iata}] Best: TWD {best_price_twd:,} on {best_date_str} ({best_airline})")
    return {
        "iata": iata,
        "price": float(best_price_twd),
        "currency": "TWD",
        "best_date": best_date_str,
        "booking_url": booking_url,
        "airline_name": best_airline or "",
        "status": "ok",
        "error_msg": None,
    }


def scrape_all(destinations: list, progress_callback=None) -> list:
    reset_rate_cache()          # Refresh exchange rate at start of each scan
    results = []
    total = len(destinations)
    for i, dest in enumerate(destinations):
        iata = dest["iata"]
        logger.info(f"Scraping {iata} ({i + 1}/{total})")
        result = scrape_destination(dest)
        results.append(result)
        if progress_callback:
            progress_callback(iata, i + 1, total, result)
        if i < total - 1:
            time.sleep(random.uniform(3.0, 6.0))
    return results
