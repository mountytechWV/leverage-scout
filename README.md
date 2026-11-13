# Leverage Scout

Search every US-listed leveraged and inverse ETF/ETN by company, ETF ticker, stock ticker, sector, industry or issuer.

## What's in here

| File | What it does |
|---|---|
| `index.html` | The app. Open it in a browser, no server needed. |
| `data/etfs.js` | The fund list the page reads. Starts as a 60-fund starter list. |
| `data/etfs.json` | Same data as JSON, handy for other tools. |
| `data/overrides.json` | Your hand fixes: company-name aliases, force include/exclude, per-fund corrections. |
| `data/cache.json` | Created on first refresh. Saves FMP lookups so the free plan's 250 calls/day go further. |
| `scripts/build_etfs.py` | Builds the full list from Massive + FMP. Standard-library Python only. |
| `refresh.bat` | Double-click on Windows to run a refresh. |
| `.github/workflows/refresh.yml` | Runs the refresh nightly on GitHub and commits the new data. |

## First run on your computer

1. Install Python 3.10+ from python.org if you don't have it (tick "Add python.exe to PATH").
2. Copy `.env.example` to `.env` and paste in your two keys. `.env` is git-ignored, so it never gets uploaded.
3. Double-click `refresh.bat`. The first run takes about 3 minutes because the free Massive plan allows 5 calls per minute.
4. Open `index.html`.

The first refresh spends up to 200 FMP calls (set by `FMP_BUDGET`). If there are more funds than that, run it again the next day and it picks up where it left off. After that, only new funds use calls.

## Put it on GitHub with nightly updates

1. Create a repo (for example `mountytechWV/leverage-scout`) and push this folder.
2. Repo **Settings > Secrets and variables > Actions > New repository secret**. Add `MASSIVE_API_KEY` and `FMP_API_KEY`.
3. **Settings > Pages**: deploy from the `main` branch, root folder.
4. **Actions** tab > "Refresh ETF list" > **Run workflow** to fill it the first time. After that it runs every weekday evening.

## How funds are found

* Massive supplies every active ETF and ETN. A fund is kept when its name shows leverage or inverse exposure: `2X`, `3X`, `-1X`, `1.75X`, ProShares `Ultra / UltraPro / UltraShort / Short`, Direxion `Bull / Bear`, or `Inverse`.
* Bond-duration and income funds that only *sound* similar (Short-Term Treasury, Ultra-Short Income, YieldMax option income) are filtered out.
* The underlying is read from the fund name: a stock ticker (`NVDA`), a company name (`Tesla`, via `aliases`), or an index/sector/commodity theme (Nasdaq-100, semiconductors, gold miners, bitcoin...).
* FMP fills in company name, sector and industry for single-stock funds, plus expense ratio, AUM and inception date when your plan includes the ETF info endpoint.

## Fixing a fund

Edit `data/overrides.json`, then refresh:

```json
"aliases": { "rocket lab": "RKLB" },
"include": ["XYZ"],
"exclude": ["ABC"],
"etfs": { "UVXY": { "lev": 1.5 }, "NEWT": { "u": "NVDA", "kind": "Single Stock" } }
```

Leveraged and inverse funds reset daily. Educational use only, not investment advice.
