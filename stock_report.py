#!/usr/bin/env python3
"""
Stock Value Tracker

Daily stock valuation HTML report + historical sheet-like storage.

Examples:
    python stock_report.py
    python stock_report.py --tickers AAPL MSFT
    python stock_report.py --override --tickers AAPL MSFT
    python stock_report.py --open-browser

Outputs:
    reports/YYYY-MM-DD/stock_report_YYYY-MM-DD.html
    reports/YYYY-MM-DD/stock_snapshot_YYYY-MM-DD.csv
    reports/latest.html

    data/valuation_history.csv
    data/valuation_history.xlsx

Notes:
    - yfinance is an unofficial Yahoo Finance data wrapper.
    - This tool is for personal research only, not investment advice.
"""

from __future__ import annotations

import argparse
import html
import math
import shutil
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


# Edit this list as your long-term default watchlist.
DEFAULT_TICKERS = [
    "GOOG",
]


# Columns shown in the HTML stock table.
# 10Y Yield is intentionally NOT repeated here because it is the same for all rows.
DISPLAY_COLUMNS = [
    "Ticker",
    "Company",
    "TTM PE",
    "Forward PE",
    "PEG",
    "PS",
    "EP",
    "Forward EP",
    "ERP",
]


# Raw daily snapshot columns.
# 10Y Yield is kept here for history, charting, and ERP auditability.
RAW_COLUMNS = [
    "Ticker",
    "Company",
    "Price",
    "Market Cap",
    "TTM PE",
    "Forward PE",
    "PEG",
    "PS",
    "EP",
    "Forward EP",
    "10Y Yield",
    "ERP",
]


# Long-term history columns.
HISTORY_COLUMNS = [
    "Date",
    "Generated At",
    "Ticker",
    "Company",
    "Price",
    "Market Cap",
    "TTM PE",
    "Forward PE",
    "PEG",
    "PS",
    "EP",
    "Forward EP",
    "10Y Yield",
    "ERP",
]


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except Exception:
        return None


def is_missing(x: Any) -> bool:
    return x is None or pd.isna(x)


def fmt_num(x: float | None, digits: int = 2) -> str:
    if is_missing(x):
        return "N/A"
    return f"{x:,.{digits}f}"


def fmt_pct(x: float | None, digits: int = 2) -> str:
    if is_missing(x):
        return "N/A"
    return f"{x * 100:.{digits}f}%"


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    result = []

    for item in items:
        ticker = item.upper().strip()
        if not ticker:
            continue
        if ticker not in seen:
            seen.add(ticker)
            result.append(ticker)

    return result


def get_last_price(ticker: yf.Ticker, info: dict[str, Any]) -> float | None:
    for key in ["currentPrice", "regularMarketPrice", "previousClose"]:
        price = safe_float(info.get(key))
        if price:
            return price

    try:
        fast_price = safe_float(ticker.fast_info.get("last_price"))
        if fast_price:
            return fast_price
    except Exception:
        pass

    try:
        hist = ticker.history(period="5d")
        if not hist.empty:
            return safe_float(hist["Close"].dropna().iloc[-1])
    except Exception:
        pass

    return None


def get_ten_year_yield() -> float | None:
    """
    Get 10-year Treasury yield from Yahoo Finance ^TNX.

    Yahoo ^TNX is commonly quoted as:
        44.5 means 4.45%, so decimal yield is 0.0445.
    """
    try:
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period="10d")

        if hist.empty:
            return None

        raw = safe_float(hist["Close"].dropna().iloc[-1])
        if raw is None:
            return None

        if raw > 20:
            return raw / 1000.0

        if raw > 1:
            return raw / 100.0

        return raw

    except Exception:
        return None


def collect_one_stock(symbol: str, ten_year_yield: float | None) -> dict[str, Any]:
    t = yf.Ticker(symbol)

    try:
        info = t.info or {}
    except Exception:
        info = {}

    price = get_last_price(t, info)
    market_cap = safe_float(info.get("marketCap"))

    trailing_eps = safe_float(info.get("trailingEps"))
    forward_eps = safe_float(info.get("forwardEps"))

    ttm_pe = safe_float(info.get("trailingPE"))
    forward_pe = safe_float(info.get("forwardPE"))

    if ttm_pe is None and price and trailing_eps and trailing_eps > 0:
        ttm_pe = price / trailing_eps

    if forward_pe is None and price and forward_eps and forward_eps > 0:
        forward_pe = price / forward_eps

    ep = None
    if price and trailing_eps and price > 0:
        ep = trailing_eps / price
    elif ttm_pe and ttm_pe > 0:
        ep = 1 / ttm_pe

    forward_ep = None
    if price and forward_eps and price > 0:
        forward_ep = forward_eps / price
    elif forward_pe and forward_pe > 0:
        forward_ep = 1 / forward_pe

    erp = None
    if forward_ep is not None and ten_year_yield is not None:
        erp = forward_ep - ten_year_yield

    return {
        "Ticker": symbol,
        "Company": info.get("shortName") or info.get("longName") or "N/A",
        "Price": price,
        "Market Cap": market_cap,
        "TTM PE": ttm_pe,
        "Forward PE": forward_pe,
        "PEG": safe_float(info.get("pegRatio")),
        "PS": safe_float(info.get("priceToSalesTrailing12Months")),
        "EP": ep,
        "Forward EP": forward_ep,
        "10Y Yield": ten_year_yield,
        "ERP": erp,
    }


def build_report(tickers: list[str]) -> pd.DataFrame:
    ten_year_yield = get_ten_year_yield()
    rows = []

    for symbol in tickers:
        try:
            rows.append(collect_one_stock(symbol, ten_year_yield))
        except Exception as e:
            rows.append({
                "Ticker": symbol,
                "Company": f"ERROR: {e}",
                "Price": None,
                "Market Cap": None,
                "TTM PE": None,
                "Forward PE": None,
                "PEG": None,
                "PS": None,
                "EP": None,
                "Forward EP": None,
                "10Y Yield": ten_year_yield,
                "ERP": None,
            })

    df = pd.DataFrame(rows)
    return df[RAW_COLUMNS]


def format_for_display(raw_df: pd.DataFrame) -> pd.DataFrame:
    out = raw_df.copy()

    out["TTM PE"] = out["TTM PE"].apply(lambda x: fmt_num(x, 2))
    out["Forward PE"] = out["Forward PE"].apply(lambda x: fmt_num(x, 2))
    out["PEG"] = out["PEG"].apply(lambda x: fmt_num(x, 2))
    out["PS"] = out["PS"].apply(lambda x: fmt_num(x, 2))
    out["EP"] = out["EP"].apply(lambda x: fmt_pct(x, 2))
    out["Forward EP"] = out["Forward EP"].apply(lambda x: fmt_pct(x, 2))
    out["ERP"] = out["ERP"].apply(lambda x: fmt_pct(x, 2))

    return out[DISPLAY_COLUMNS]


def metric_class(column: str, raw_value: float | None) -> str:
    """
    Basic visual hints.

    These are not buy/sell signals.
    They only make the table easier to scan.
    """
    if raw_value is None or pd.isna(raw_value):
        return "neutral"

    if column == "ERP":
        if raw_value >= 0.03:
            return "good"
        if raw_value >= 0.00:
            return "okay"
        return "bad"

    if column == "Forward EP":
        if raw_value >= 0.06:
            return "good"
        if raw_value >= 0.04:
            return "okay"
        return "bad"

    if column == "EP":
        if raw_value >= 0.06:
            return "good"
        if raw_value >= 0.04:
            return "okay"
        return "bad"

    if column == "PEG":
        if raw_value <= 1.0:
            return "good"
        if raw_value <= 2.0:
            return "okay"
        return "bad"

    return "neutral"


def html_cell(column: str, display_value: str, raw_value: Any) -> str:
    cls = metric_class(column, raw_value if isinstance(raw_value, float) else safe_float(raw_value))

    if column == "Ticker":
        return f'<td class="ticker">{html.escape(display_value)}</td>'

    if column == "Company":
        return f'<td class="company">{html.escape(display_value)}</td>'

    return f'<td><span class="pill {cls}">{html.escape(display_value)}</span></td>'


def generate_html_report(
    raw_df: pd.DataFrame,
    display_df: pd.DataFrame,
    tickers: list[str],
    as_of_date: str,
    generated_at: str,
) -> str:
    ten_year_yield = None
    if not raw_df.empty and "10Y Yield" in raw_df.columns:
        ten_year_yield = safe_float(raw_df["10Y Yield"].iloc[0])

    rows_html = []

    for idx, display_row in display_df.iterrows():
        raw_row = raw_df.iloc[idx]
        cells = []

        for col in DISPLAY_COLUMNS:
            cells.append(html_cell(col, str(display_row[col]), raw_row[col]))

        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    table_header = "".join(f"<th>{html.escape(col)}</th>" for col in DISPLAY_COLUMNS)

    ticker_badges = " ".join(
        f'<span class="ticker-badge">{html.escape(t)}</span>' for t in tickers
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Stock Valuation Report - {as_of_date}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {{
      --bg: #0f172a;
      --card: #111827;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --border: #374151;
      --good-bg: #064e3b;
      --good-text: #a7f3d0;
      --okay-bg: #78350f;
      --okay-text: #fde68a;
      --bad-bg: #7f1d1d;
      --bad-text: #fecaca;
      --neutral-bg: #374151;
      --neutral-text: #e5e7eb;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      padding: 32px;
      background: linear-gradient(135deg, #020617, #111827);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}

    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}

    h1 {{
      margin: 0 0 8px 0;
      font-size: 32px;
      letter-spacing: -0.03em;
    }}

    .subtitle {{
      color: var(--muted);
      font-size: 14px;
    }}

    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin: 24px 0;
    }}

    .card {{
      background: rgba(17, 24, 39, 0.88);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.25);
    }}

    .card-label {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}

    .card-value {{
      font-size: 24px;
      font-weight: 700;
    }}

    .ticker-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }}

    .ticker-badge {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      background: #1e293b;
      color: #bfdbfe;
      border: 1px solid #334155;
      font-size: 13px;
      font-weight: 600;
    }}

    .table-wrap {{
      overflow-x: auto;
      background: rgba(17, 24, 39, 0.88);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.25);
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 820px;
    }}

    th {{
      text-align: left;
      color: #cbd5e1;
      font-size: 13px;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      background: #020617;
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
    }}

    td {{
      padding: 14px 16px;
      border-bottom: 1px solid rgba(55, 65, 81, 0.7);
      font-size: 14px;
      white-space: nowrap;
    }}

    tr:hover {{
      background: rgba(30, 41, 59, 0.7);
    }}

    .ticker {{
      font-weight: 800;
      color: #93c5fd;
    }}

    .company {{
      color: #d1d5db;
      min-width: 220px;
    }}

    .pill {{
      display: inline-block;
      min-width: 72px;
      text-align: right;
      padding: 5px 9px;
      border-radius: 999px;
      font-variant-numeric: tabular-nums;
      font-weight: 650;
    }}

    .good {{
      background: var(--good-bg);
      color: var(--good-text);
    }}

    .okay {{
      background: var(--okay-bg);
      color: var(--okay-text);
    }}

    .bad {{
      background: var(--bad-bg);
      color: var(--bad-text);
    }}

    .neutral {{
      background: var(--neutral-bg);
      color: var(--neutral-text);
    }}

    .notes {{
      margin-top: 24px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }}

    .notes code {{
      color: #dbeafe;
      background: #1e293b;
      padding: 2px 6px;
      border-radius: 6px;
    }}

    @media print {{
      body {{
        background: white;
        color: black;
        padding: 16px;
      }}

      .card, .table-wrap {{
        box-shadow: none;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Stock Valuation Report</h1>
    <div class="subtitle">As of {html.escape(as_of_date)} · Generated at {html.escape(generated_at)}</div>

    <div class="cards">
      <div class="card">
        <div class="card-label">Tracked Stocks</div>
        <div class="card-value">{len(tickers)}</div>
        <div class="ticker-badges">{ticker_badges}</div>
      </div>

      <div class="card">
        <div class="card-label">10Y Treasury Yield</div>
        <div class="card-value">{fmt_pct(ten_year_yield)}</div>
      </div>

      <div class="card">
        <div class="card-label">ERP Formula</div>
        <div class="card-value" style="font-size: 18px;">Forward EP - 10Y Yield</div>
      </div>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>{table_header}</tr>
        </thead>
        <tbody>
          {"".join(rows_html)}
        </tbody>
      </table>
    </div>

    <div class="notes">
      <p><strong>Formula Notes</strong></p>
      <p><code>EP</code> = Earnings Yield = EPS / Price = 1 / PE.</p>
      <p><code>Forward EP</code> = Forward EPS / Price = 1 / Forward PE.</p>
      <p><code>ERP</code> = Forward EP - 10Y Treasury Yield.</p>
      <p><code>10Y Yield</code> is shown once at the top because it is the same for all stocks. It is still saved in the CSV/XLSX history for future charting and analysis.</p>
      <p>The long-term history is stored in <code>data/valuation_history.csv</code> and, if Excel export succeeds, <code>data/valuation_history.xlsx</code>.</p>
      <p>Green / yellow / red colors are only visual scanning aids, not buy or sell signals.</p>
      <p>Data source: Yahoo Finance via yfinance. Forward PE, PEG, and Forward EPS depend on analyst estimate availability.</p>
    </div>
  </div>
</body>
</html>
"""


def save_history(
    raw_df: pd.DataFrame,
    as_of_date: str,
    generated_at: str,
    data_dir: str,
    export_excel: bool = True,
) -> tuple[Path, Path | None]:
    """
    Append today's raw numeric data to long-term CSV/XLSX history.

    If the script runs multiple times on the same date, same ticker rows are replaced,
    not duplicated.
    """
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    history_csv_path = Path(data_dir) / "valuation_history.csv"
    history_xlsx_path = Path(data_dir) / "valuation_history.xlsx"

    today_df = raw_df.copy()
    today_df.insert(0, "Generated At", generated_at)
    today_df.insert(0, "Date", as_of_date)
    today_df = today_df[HISTORY_COLUMNS]

    if history_csv_path.exists():
        old_df = pd.read_csv(history_csv_path)
        combined = pd.concat([old_df, today_df], ignore_index=True)
    else:
        combined = today_df

    combined["Date"] = combined["Date"].astype(str)
    combined["Ticker"] = combined["Ticker"].astype(str)

    combined = combined.drop_duplicates(
        subset=["Date", "Ticker"],
        keep="last",
    )

    combined = combined.sort_values(["Date", "Ticker"]).reset_index(drop=True)

    combined.to_csv(history_csv_path, index=False)

    if not export_excel:
        return history_csv_path, None

    try:
        with pd.ExcelWriter(history_xlsx_path, engine="openpyxl") as writer:
            combined.to_excel(writer, sheet_name="History", index=False)
            today_df.to_excel(writer, sheet_name="Latest", index=False)
        return history_csv_path, history_xlsx_path
    except Exception as e:
        print(f"Warning: Excel export failed. CSV history was still saved. Error: {e}")
        return history_csv_path, None


def save_daily_reports(
    raw_df: pd.DataFrame,
    display_df: pd.DataFrame,
    tickers: list[str],
    output_dir: str,
    as_of_date: str,
    generated_at: str,
) -> tuple[Path, Path, Path]:
    daily_dir = Path(output_dir) / as_of_date
    daily_dir.mkdir(parents=True, exist_ok=True)

    html_path = daily_dir / f"stock_report_{as_of_date}.html"
    snapshot_csv_path = daily_dir / f"stock_snapshot_{as_of_date}.csv"
    latest_html_path = Path(output_dir) / "latest.html"

    raw_df.to_csv(snapshot_csv_path, index=False)

    html_content = generate_html_report(
        raw_df=raw_df,
        display_df=display_df,
        tickers=tickers,
        as_of_date=as_of_date,
        generated_at=generated_at,
    )

    html_path.write_text(html_content, encoding="utf-8")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(html_path, latest_html_path)

    return html_path, snapshot_csv_path, latest_html_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--tickers",
        nargs="+",
        default=[],
        help=(
            "Ticker symbols from command line. "
            "By default these are appended to DEFAULT_TICKERS. "
            "Use --override to ignore DEFAULT_TICKERS."
        ),
    )

    parser.add_argument(
        "--override",
        action="store_true",
        help="Use only command-line tickers and ignore DEFAULT_TICKERS.",
    )

    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Directory to save daily HTML and snapshot reports.",
    )

    parser.add_argument(
        "--data-dir",
        default="data",
        help="Directory to save long-term CSV/XLSX history.",
    )

    parser.add_argument(
        "--as-of-date",
        default=None,
        help="Override report date, format YYYY-MM-DD. Useful for backfill/testing.",
    )

    parser.add_argument(
        "--no-excel",
        action="store_true",
        help="Skip XLSX export and only update the CSV history file.",
    )

    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the generated HTML report in your default browser.",
    )

    return parser.parse_args()


def get_final_ticker_list(args: argparse.Namespace) -> list[str]:
    command_line_tickers = args.tickers

    if args.override:
        if not command_line_tickers:
            raise ValueError("You used --override but did not provide any --tickers.")
        return dedupe_keep_order(command_line_tickers)

    return dedupe_keep_order(DEFAULT_TICKERS + command_line_tickers)


def main() -> None:
    args = parse_args()

    tickers = get_final_ticker_list(args)

    as_of_date = args.as_of_date or datetime.now().strftime("%Y-%m-%d")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    raw_df = build_report(tickers)
    display_df = format_for_display(raw_df)

    html_path, snapshot_csv_path, latest_html_path = save_daily_reports(
        raw_df=raw_df,
        display_df=display_df,
        tickers=tickers,
        output_dir=args.output_dir,
        as_of_date=as_of_date,
        generated_at=generated_at,
    )

    history_csv_path, history_xlsx_path = save_history(
        raw_df=raw_df,
        as_of_date=as_of_date,
        generated_at=generated_at,
        data_dir=args.data_dir,
        export_excel=not args.no_excel,
    )

    print(f"Saved daily HTML report: {html_path}")
    print(f"Saved latest HTML copy:   {latest_html_path}")
    print(f"Saved daily CSV snapshot: {snapshot_csv_path}")
    print(f"Updated history CSV:      {history_csv_path}")
    if history_xlsx_path is not None:
        print(f"Updated history Excel:    {history_xlsx_path}")
    else:
        print("Updated history Excel:    skipped or failed")

    if args.open_browser:
        webbrowser.open(html_path.resolve().as_uri())


if __name__ == "__main__":
    main()
