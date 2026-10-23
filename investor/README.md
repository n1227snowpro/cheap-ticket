# StockRadar — US investor dashboard

Scans prices, fundamentals, SEC insider filings, news and social media, then scores every
S&P 500 / Nasdaq-100 stock on **Value**, **Growth**, **Quality** and **Momentum & sentiment**
(0–100, percentile vs. sector peers), tags it with an investing style, and explains *why* in
plain English. Educational only — not financial advice.

## Pages
| Page | What it does |
|---|---|
| **Today** (`/`) | SPY + sector strip, AI morning brief, Top value / Top growth / Insiders buying / Buzzing now |
| **Screener** (`/screener`) | One-click presets (Buffett, Graham Defensive, GARP, Hypergrowth, Dividend, Deep Value, Quality Momentum) + score sliders, sector, P/E, yield, tag filters; sortable table |
| **Stock** (`/stock/<T>`) | Score gauges, reasons, fair-value estimates (Graham, DCF, analyst), price vs S&P, indicator checklist, financials, social buzz, news, insider trades, peers |
| **News & Social** (`/feed`) | Headlines + Reddit/StockTwits posts tagged by ticker and tone |
| **Watchlist** (`/watchlist`) | ★ stocks saved in the browser |
| **How it works** (`/learn`) | Every indicator explained |

## Indicators
Value: P/E, P/B, P/FCF, EV/EBITDA, Graham Number, 2-stage DCF margin of safety, FCF & dividend yield.
Growth: 3y revenue/EPS CAGR, forward EPS growth, 90-day estimate revisions, PEG, gross-margin trend, Rule of 40.
Quality: ROIC, ROE, Piotroski F-Score, Altman Z, margin stability, FCF conversion, dilution, debt/equity.
Momentum & sentiment: 12m return vs S&P 500, 6m return, 52-week position, news tone, social buzz z-score, insider buyers.

## Data sources
| Data | Source | Key |
|---|---|---|
| Prices, fundamentals, estimates, news | [EODHD](https://eodhd.com) All-In-One | `EODHD_KEY` (required for live data) |
| Insider trades (Form 4) | SEC EDGAR | `SEC_USER_AGENT` (your contact e-mail) |
| Reddit mentions | Reddit API (script app) | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` |
| StockTwits sentiment | public API | — |
| Headline summaries + morning brief | Claude API | `ANTHROPIC_KEY` (optional) |

Keys can be env vars or entries (lower-case) in `$INVESTOR_DATA/config.json`.
**Without `EODHD_KEY` the app runs in demo mode on fictional companies with synthetic numbers**
(a banner says so), so you can try it with zero setup.

Refresh cadence: fundamentals weekly, prices/insiders/digest daily, news hourly, social every 20 min.
Manual trigger: `curl -X POST 'localhost:9003/api/refresh?job=news'`.

## Run
```bash
cd investor
pip install -r requirements-dev.txt
python3 app.py            # → http://localhost:9003
pytest -q                 # unit + API tests (demo data, no network)
```
With Docker, the root `docker-compose.yml` has a `stockradar` service
(`invest.srv1213330.hstgr.cloud`); put keys in a `.env` file next to it.

## Code map
`metrics.py` indicator formulas · `scoring.py` percentiles, tags, presets ·
`providers/` EODHD, SEC, Reddit/StockTwits, Claude · `scheduler.py` background jobs ·
`db.py` SQLite · `fixtures.py` demo data · `app.py` routes · `templates/`, `static/` UI.
