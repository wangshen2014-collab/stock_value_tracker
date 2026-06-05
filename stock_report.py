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
    reports/YYYY-MM-DD/pe_valuation_snapshot_YYYY-MM-DD.csv
    reports/latest.html

    data/valuation_history.csv
    data/valuation_history.xlsx
    data/pe_valuation_history.csv
    data/pe_valuation_history.xlsx

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


# Columns shown in the main HTML stock table.
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
    "TTM EPS",
    "Forward EPS",
    "TTM PE",
    "Forward PE",
    "PEG",
    "PS",
    "EP",
    "Forward EP",
    "10Y Yield",
    "ERP",
]


# Long-term main valuation history columns.
HISTORY_COLUMNS = [
    "Date",
    "Generated At",
    "Ticker",
    "Company",
    "Price",
    "Market Cap",
    "TTM EPS",
    "Forward EPS",
    "TTM PE",
    "Forward PE",
    "PEG",
    "PS",
    "EP",
    "Forward EP",
    "10Y Yield",
    "ERP",
]


PE_WINDOWS = [90, 180]
MIN_PE_OBSERVATIONS = 20


PE_ANALYSIS_RAW_COLUMNS = [
    "Ticker",
    "Company",
    "Status",
    "Method",
    "Current Price",
    "Current TTM EPS",
    "Current TTM PE",
    "Historical EPS Reports Used",
]

for _window in PE_WINDOWS:
    PE_ANALYSIS_RAW_COLUMNS.extend([
        f"PE_{_window}D_Count",
        f"PE_{_window}D_Min",
        f"PE_{_window}D_Max",
        f"PE_{_window}D_Mean",
        f"PE_{_window}D_Median",
        f"PE_{_window}D_Std",
        f"PE_{_window}D_P10",
        f"PE_{_window}D_P90",
        f"PE_{_window}D_Current_ZScore",
        f"PE_{_window}D_Current_Percentile",
        f"Value_{_window}D_Min",
        f"Value_{_window}D_Max",
        f"Value_{_window}D_Mean",
        f"Value_{_window}D_Lower_1Std",
        f"Value_{_window}D_Upper_1Std",
        f"Value_{_window}D_P10",
        f"Value_{_window}D_P90",
    ])


PE_ANALYSIS_HISTORY_COLUMNS = [
    "Date",
    "Generated At",
] + PE_ANALYSIS_RAW_COLUMNS


PE_DISPLAY_COLUMNS = [
    "Ticker",
    "Status",
    "Current PE",
    "EPS Used",
    "90D PE Range",
    "90D PE P10-P90",
    "90D PE Std",
    "90D PE Z",
    "90D Value Range",
    "90D Normal Value",
    "180D PE Range",
    "180D PE P10-P90",
    "180D PE Std",
    "180D PE Z",
    "180D Value Range",
    "180D Normal Value",
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


def fmt_money(x: float | None, digits: int = 2) -> str:
    if is_missing(x):
        return "N/A"
    return f"${x:,.{digits}f}"


def fmt_range(low: float | None, high: float | None, digits: int = 2, money: bool = False) -> str:
    if is_missing(low) or is_missing(high):
        return "N/A"
    if money:
        return f"{fmt_money(low, digits)} - {fmt_money(high, digits)}"
    return f"{fmt_num(low, digits)} - {fmt_num(high, digits)}"


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
        hist = ticker.history(period="5d", auto_adjust=False)
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
        hist = tnx.history(period="10d", auto_adjust=False)

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

    if trailing_eps is None and price and ttm_pe and ttm_pe > 0:
        trailing_eps = price / ttm_pe

    if forward_eps is None and price and forward_pe and forward_pe > 0:
        forward_eps = price / forward_pe

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
        "TTM EPS": trailing_eps,
        "Forward EPS": forward_eps,
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
                "TTM EPS": None,
                "Forward EPS": None,
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
    return df.reindex(columns=RAW_COLUMNS)


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


def get_quarterly_eps_history(ticker: yf.Ticker) -> pd.DataFrame:
    """
    Build a point-in-time TTM EPS series from reported quarterly EPS.

    Method:
        1. Use yfinance earnings dates.
        2. Keep rows with actual reported quarterly EPS.
        3. Sort by earnings report date.
        4. Rolling-sum the latest 4 reported quarters to estimate TTM EPS.

    Limitation:
        yfinance does not always expose complete historical EPS dates for all symbols.
        The report date is treated as the first available date; after-market timing is not modeled.
    """
    try:
        earnings = ticker.get_earnings_dates(limit=32)
    except Exception:
        earnings = None

    if earnings is None or earnings.empty:
        return pd.DataFrame(columns=["Report Date", "Quarterly EPS", "Point-in-Time TTM EPS"])

    df = earnings.reset_index()
    date_col = df.columns[0]

    eps_col = None
    for col in df.columns:
        col_l = str(col).lower()
        if "eps actual" in col_l or "reported eps" in col_l:
            eps_col = col
            break

    if eps_col is None:
        return pd.DataFrame(columns=["Report Date", "Quarterly EPS", "Point-in-Time TTM EPS"])

    out = pd.DataFrame()
    out["Report Date"] = pd.to_datetime(df[date_col], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    out["Quarterly EPS"] = pd.to_numeric(df[eps_col], errors="coerce")
    out = out.dropna(subset=["Report Date", "Quarterly EPS"])
    out = out.sort_values("Report Date")
    out = out.drop_duplicates(subset=["Report Date"], keep="last")
    out["Point-in-Time TTM EPS"] = out["Quarterly EPS"].rolling(window=4).sum()
    out = out.dropna(subset=["Point-in-Time TTM EPS"])
    return out[["Report Date", "Quarterly EPS", "Point-in-Time TTM EPS"]]


def get_price_history_for_pe(ticker: yf.Ticker) -> pd.DataFrame:
    try:
        hist = ticker.history(period="1y", auto_adjust=False)
    except Exception:
        hist = pd.DataFrame()

    if hist.empty or "Close" not in hist.columns:
        return pd.DataFrame(columns=["Date", "Close"])

    out = hist.reset_index()
    date_col = "Date" if "Date" in out.columns else out.columns[0]
    out["Date"] = pd.to_datetime(out[date_col], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    out["Close"] = pd.to_numeric(out["Close"], errors="coerce")
    out = out.dropna(subset=["Date", "Close"])
    out = out.sort_values("Date")
    return out[["Date", "Close"]]


def empty_pe_analysis_row(symbol: str, company: str, status: str) -> dict[str, Any]:
    row = {col: None for col in PE_ANALYSIS_RAW_COLUMNS}
    row.update({
        "Ticker": symbol,
        "Company": company,
        "Status": status,
        "Method": "Point-in-time TTM EPS from reported quarterly EPS; historical PE = close / then-known TTM EPS",
    })
    return row


def add_window_stats(
    row: dict[str, Any],
    window: int,
    pe_series: pd.Series,
    current_pe: float | None,
    current_ttm_eps: float | None,
) -> None:
    prefix = f"PE_{window}D"
    value_prefix = f"Value_{window}D"
    pe_series = pe_series.dropna()
    pe_series = pe_series[pe_series > 0]
    count = int(len(pe_series))
    row[f"{prefix}_Count"] = count

    if count < MIN_PE_OBSERVATIONS:
        return

    pe_min = safe_float(pe_series.min())
    pe_max = safe_float(pe_series.max())
    pe_mean = safe_float(pe_series.mean())
    pe_median = safe_float(pe_series.median())
    pe_std = safe_float(pe_series.std(ddof=1)) if count >= 2 else None
    pe_p10 = safe_float(pe_series.quantile(0.10))
    pe_p90 = safe_float(pe_series.quantile(0.90))

    row[f"{prefix}_Min"] = pe_min
    row[f"{prefix}_Max"] = pe_max
    row[f"{prefix}_Mean"] = pe_mean
    row[f"{prefix}_Median"] = pe_median
    row[f"{prefix}_Std"] = pe_std
    row[f"{prefix}_P10"] = pe_p10
    row[f"{prefix}_P90"] = pe_p90

    if current_pe is not None and pe_std is not None and pe_std > 0 and pe_mean is not None:
        row[f"{prefix}_Current_ZScore"] = (current_pe - pe_mean) / pe_std

    if current_pe is not None:
        row[f"{prefix}_Current_Percentile"] = float((pe_series <= current_pe).sum() / count)

    if current_ttm_eps is not None and current_ttm_eps > 0:
        row[f"{value_prefix}_Min"] = pe_min * current_ttm_eps if pe_min is not None else None
        row[f"{value_prefix}_Max"] = pe_max * current_ttm_eps if pe_max is not None else None
        row[f"{value_prefix}_Mean"] = pe_mean * current_ttm_eps if pe_mean is not None else None
        row[f"{value_prefix}_P10"] = pe_p10 * current_ttm_eps if pe_p10 is not None else None
        row[f"{value_prefix}_P90"] = pe_p90 * current_ttm_eps if pe_p90 is not None else None

        if pe_mean is not None and pe_std is not None:
            row[f"{value_prefix}_Lower_1Std"] = max(0.0, (pe_mean - pe_std) * current_ttm_eps)
            row[f"{value_prefix}_Upper_1Std"] = (pe_mean + pe_std) * current_ttm_eps


def collect_one_pe_analysis(symbol: str, base_row: pd.Series, as_of_date: str) -> dict[str, Any]:
    company = str(base_row.get("Company", "N/A"))
    row = empty_pe_analysis_row(symbol, company, "OK")

    current_price = safe_float(base_row.get("Price"))
    current_ttm_eps = safe_float(base_row.get("TTM EPS"))
    current_pe = safe_float(base_row.get("TTM PE"))

    if current_ttm_eps is None and current_price and current_pe and current_pe > 0:
        current_ttm_eps = current_price / current_pe

    if current_pe is None and current_price and current_ttm_eps and current_ttm_eps > 0:
        current_pe = current_price / current_ttm_eps

    row["Current Price"] = current_price
    row["Current TTM EPS"] = current_ttm_eps
    row["Current TTM PE"] = current_pe

    if current_ttm_eps is None or current_ttm_eps <= 0:
        row["Status"] = "No positive current TTM EPS; PE analysis skipped"
        return row

    if current_pe is None or current_pe <= 0:
        row["Status"] = "No positive current PE; PE analysis skipped"
        return row

    ticker = yf.Ticker(symbol)
    eps_df = get_quarterly_eps_history(ticker)
    row["Historical EPS Reports Used"] = int(len(eps_df))

    if eps_df.empty or len(eps_df) < 2:
        row["Status"] = "Not enough reported EPS history from yfinance"
        return row

    price_df = get_price_history_for_pe(ticker)
    if price_df.empty:
        row["Status"] = "No historical close price data from yfinance"
        return row

    merged = pd.merge_asof(
        price_df.sort_values("Date"),
        eps_df[["Report Date", "Point-in-Time TTM EPS"]].sort_values("Report Date"),
        left_on="Date",
        right_on="Report Date",
        direction="backward",
    )

    merged = merged.dropna(subset=["Close", "Point-in-Time TTM EPS"])
    merged = merged[merged["Point-in-Time TTM EPS"] > 0]

    if merged.empty:
        row["Status"] = "No positive point-in-time TTM EPS available for price history"
        return row

    merged["Historical PE"] = merged["Close"] / merged["Point-in-Time TTM EPS"]

    as_of_ts = pd.to_datetime(as_of_date, errors="coerce")
    if pd.isna(as_of_ts):
        as_of_ts = pd.Timestamp.today().normalize()

    for window in PE_WINDOWS:
        cutoff = as_of_ts - pd.Timedelta(days=window)
        window_df = merged[merged["Date"] >= cutoff]
        add_window_stats(row, window, window_df["Historical PE"], current_pe, current_ttm_eps)

    counts = [safe_float(row.get(f"PE_{window}D_Count")) or 0 for window in PE_WINDOWS]
    if max(counts) < MIN_PE_OBSERVATIONS:
        row["Status"] = "Not enough PE observations in requested windows"

    return row


def build_pe_analysis(raw_df: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    rows = []
    for _, base_row in raw_df.iterrows():
        symbol = str(base_row.get("Ticker", "")).upper().strip()
        if not symbol:
            continue
        try:
            rows.append(collect_one_pe_analysis(symbol, base_row, as_of_date))
        except Exception as e:
            rows.append(empty_pe_analysis_row(symbol, str(base_row.get("Company", "N/A")), f"ERROR: {e}"))

    if not rows:
        return pd.DataFrame(columns=PE_ANALYSIS_RAW_COLUMNS)

    return pd.DataFrame(rows).reindex(columns=PE_ANALYSIS_RAW_COLUMNS)


def format_pe_analysis_for_display(pe_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in pe_df.iterrows():
        rows.append({
            "Ticker": row.get("Ticker"),
            "Status": row.get("Status"),
            "Current PE": fmt_num(safe_float(row.get("Current TTM PE")), 2),
            "EPS Used": fmt_num(safe_float(row.get("Current TTM EPS")), 2),
            "90D PE Range": fmt_range(row.get("PE_90D_Min"), row.get("PE_90D_Max"), 2),
            "90D PE P10-P90": fmt_range(row.get("PE_90D_P10"), row.get("PE_90D_P90"), 2),
            "90D PE Std": fmt_num(safe_float(row.get("PE_90D_Std")), 2),
            "90D PE Z": fmt_num(safe_float(row.get("PE_90D_Current_ZScore")), 2),
            "90D Value Range": fmt_range(row.get("Value_90D_Min"), row.get("Value_90D_Max"), 2, money=True),
            "90D Normal Value": fmt_range(row.get("Value_90D_P10"), row.get("Value_90D_P90"), 2, money=True),
            "180D PE Range": fmt_range(row.get("PE_180D_Min"), row.get("PE_180D_Max"), 2),
            "180D PE P10-P90": fmt_range(row.get("PE_180D_P10"), row.get("PE_180D_P90"), 2),
            "180D PE Std": fmt_num(safe_float(row.get("PE_180D_Std")), 2),
            "180D PE Z": fmt_num(safe_float(row.get("PE_180D_Current_ZScore")), 2),
            "180D Value Range": fmt_range(row.get("Value_180D_Min"), row.get("Value_180D_Max"), 2, money=True),
            "180D Normal Value": fmt_range(row.get("Value_180D_P10"), row.get("Value_180D_P90"), 2, money=True),
        })

    return pd.DataFrame(rows).reindex(columns=PE_DISPLAY_COLUMNS)


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

    if column in ["Forward EP", "EP"]:
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


def zscore_class(raw_value: float | None) -> str:
    if raw_value is None or pd.isna(raw_value):
        return "neutral"
    if raw_value <= -1.0:
        return "good"
    if raw_value <= 1.0:
        return "okay"
    return "bad"


def html_cell(column: str, display_value: str, raw_value: Any) -> str:
    cls = metric_class(column, raw_value if isinstance(raw_value, float) else safe_float(raw_value))

    if column == "Ticker":
        return f'<td class="ticker">{html.escape(display_value)}</td>'

    if column == "Company":
        return f'<td class="company">{html.escape(display_value)}</td>'

    return f'<td><span class="pill {cls}">{html.escape(display_value)}</span></td>'


def pe_html_cell(column: str, display_value: str, raw_row: pd.Series) -> str:
    if column == "Ticker":
        return f'<td class="ticker">{html.escape(display_value)}</td>'

    if column == "Status":
        cls = "good" if display_value == "OK" else "bad"
        return f'<td><span class="pill {cls}">{html.escape(display_value)}</span></td>'

    raw_value = None
    if column == "90D PE Z":
        raw_value = safe_float(raw_row.get("PE_90D_Current_ZScore"))
        cls = zscore_class(raw_value)
        return f'<td><span class="pill {cls}">{html.escape(display_value)}</span></td>'

    if column == "180D PE Z":
        raw_value = safe_float(raw_row.get("PE_180D_Current_ZScore"))
        cls = zscore_class(raw_value)
        return f'<td><span class="pill {cls}">{html.escape(display_value)}</span></td>'

    return f'<td>{html.escape(display_value)}</td>'


def build_main_table_html(raw_df: pd.DataFrame, display_df: pd.DataFrame) -> str:
    rows_html = []
    for idx, display_row in display_df.iterrows():
        raw_row = raw_df.iloc[idx]
        cells = []
        for col in DISPLAY_COLUMNS:
            cells.append(html_cell(col, str(display_row[col]), raw_row[col]))
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    table_header = "".join(f"<th>{html.escape(col)}</th>" for col in DISPLAY_COLUMNS)
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr>{table_header}</tr></thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
    </div>
    """


def build_pe_table_html(pe_raw_df: pd.DataFrame, pe_display_df: pd.DataFrame) -> str:
    rows_html = []
    for idx, display_row in pe_display_df.iterrows():
        raw_row = pe_raw_df.iloc[idx]
        cells = []
        for col in PE_DISPLAY_COLUMNS:
            cells.append(pe_html_cell(col, str(display_row[col]), raw_row))
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    table_header = "".join(f"<th>{html.escape(col)}</th>" for col in PE_DISPLAY_COLUMNS)
    return f"""
    <div class="table-wrap pe-table-wrap">
      <table>
        <thead><tr>{table_header}</tr></thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
    </div>
    """


def generate_html_report(
    raw_df: pd.DataFrame,
    display_df: pd.DataFrame,
    pe_raw_df: pd.DataFrame,
    pe_display_df: pd.DataFrame,
    tickers: list[str],
    as_of_date: str,
    generated_at: str,
) -> str:
    ten_year_yield = None
    if not raw_df.empty and "10Y Yield" in raw_df.columns:
        ten_year_yield = safe_float(raw_df["10Y Yield"].iloc[0])

    ticker_badges = " ".join(
        f'<span class="ticker-badge">{html.escape(t)}</span>' for t in tickers
    )

    main_table_html = build_main_table_html(raw_df, display_df)
    pe_table_html = build_pe_table_html(pe_raw_df, pe_display_df)

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
      max-width: 1300px;
      margin: 0 auto;
    }}

    h1 {{
      margin: 0 0 8px 0;
      font-size: 32px;
      letter-spacing: -0.03em;
    }}

    h2 {{
      margin: 30px 0 12px 0;
      font-size: 20px;
      letter-spacing: -0.02em;
    }}

    .subtitle {{
      color: var(--muted);
      font-size: 14px;
    }}

    .section-note {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
      margin: -4px 0 12px 0;
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
      min-width: 860px;
    }}

    .pe-table-wrap table {{
      min-width: 1500px;
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

    .notes code, .section-note code {{
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

    <h2>Current Valuation Snapshot</h2>
    {main_table_html}

    <h2>Point-in-Time PE Volatility & Valuation Range</h2>
    <div class="section-note">
      Historical PE is reconstructed as <code>daily close / then-known TTM EPS</code> using reported quarterly EPS dates. Value ranges translate the historical PE range back into price using today's TTM EPS.
    </div>
    {pe_table_html}

    <div class="notes">
      <p><strong>Formula Notes</strong></p>
      <p><code>EP</code> = Earnings Yield = EPS / Price = 1 / PE.</p>
      <p><code>Forward EP</code> = Forward EPS / Price = 1 / Forward PE.</p>
      <p><code>ERP</code> = Forward EP - 10Y Treasury Yield.</p>
      <p><code>PE Z</code> = (Current PE - historical PE mean) / historical PE standard deviation.</p>
      <p><code>Value Range</code> = historical PE min/max multiplied by current TTM EPS.</p>
      <p><code>Normal Value</code> = historical PE P10/P90 multiplied by current TTM EPS; it is usually more stable than min/max.</p>
      <p><code>10Y Yield</code> is shown once at the top because it is the same for all stocks. It is still saved in the CSV/XLSX history for future charting and analysis.</p>
      <p>Main valuation history is stored in <code>data/valuation_history.csv</code>. PE volatility history is stored in <code>data/pe_valuation_history.csv</code>.</p>
      <p>Green / yellow / red colors are only visual scanning aids, not buy or sell signals.</p>
      <p>Data source: Yahoo Finance via yfinance. Forward PE, PEG, Forward EPS, and reported EPS dates depend on data availability.</p>
    </div>
  </div>
</body>
</html>
"""


def merge_and_dedupe_history(
    today_df: pd.DataFrame,
    history_path: Path,
    columns: list[str],
) -> pd.DataFrame:
    if history_path.exists():
        old_df = pd.read_csv(history_path)
        combined = pd.concat([old_df, today_df], ignore_index=True)
    else:
        combined = today_df

    combined = combined.reindex(columns=columns)
    combined["Date"] = combined["Date"].astype(str)
    combined["Ticker"] = combined["Ticker"].astype(str)
    combined = combined.drop_duplicates(subset=["Date", "Ticker"], keep="last")
    combined = combined.sort_values(["Date", "Ticker"]).reset_index(drop=True)
    return combined


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
    today_df = today_df.reindex(columns=HISTORY_COLUMNS)

    combined = merge_and_dedupe_history(today_df, history_csv_path, HISTORY_COLUMNS)
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


def save_pe_history(
    pe_raw_df: pd.DataFrame,
    as_of_date: str,
    generated_at: str,
    data_dir: str,
    export_excel: bool = True,
) -> tuple[Path, Path | None]:
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    history_csv_path = Path(data_dir) / "pe_valuation_history.csv"
    history_xlsx_path = Path(data_dir) / "pe_valuation_history.xlsx"

    today_df = pe_raw_df.copy()
    today_df.insert(0, "Generated At", generated_at)
    today_df.insert(0, "Date", as_of_date)
    today_df = today_df.reindex(columns=PE_ANALYSIS_HISTORY_COLUMNS)

    combined = merge_and_dedupe_history(today_df, history_csv_path, PE_ANALYSIS_HISTORY_COLUMNS)
    combined.to_csv(history_csv_path, index=False)

    if not export_excel:
        return history_csv_path, None

    try:
        with pd.ExcelWriter(history_xlsx_path, engine="openpyxl") as writer:
            combined.to_excel(writer, sheet_name="History", index=False)
            today_df.to_excel(writer, sheet_name="Latest", index=False)
        return history_csv_path, history_xlsx_path
    except Exception as e:
        print(f"Warning: PE Excel export failed. CSV history was still saved. Error: {e}")
        return history_csv_path, None


def save_daily_reports(
    raw_df: pd.DataFrame,
    display_df: pd.DataFrame,
    pe_raw_df: pd.DataFrame,
    pe_display_df: pd.DataFrame,
    tickers: list[str],
    output_dir: str,
    as_of_date: str,
    generated_at: str,
) -> tuple[Path, Path, Path, Path]:
    daily_dir = Path(output_dir) / as_of_date
    daily_dir.mkdir(parents=True, exist_ok=True)

    html_path = daily_dir / f"stock_report_{as_of_date}.html"
    snapshot_csv_path = daily_dir / f"stock_snapshot_{as_of_date}.csv"
    pe_snapshot_csv_path = daily_dir / f"pe_valuation_snapshot_{as_of_date}.csv"
    latest_html_path = Path(output_dir) / "latest.html"

    raw_df.to_csv(snapshot_csv_path, index=False)
    pe_raw_df.to_csv(pe_snapshot_csv_path, index=False)

    html_content = generate_html_report(
        raw_df=raw_df,
        display_df=display_df,
        pe_raw_df=pe_raw_df,
        pe_display_df=pe_display_df,
        tickers=tickers,
        as_of_date=as_of_date,
        generated_at=generated_at,
    )

    html_path.write_text(html_content, encoding="utf-8")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(html_path, latest_html_path)

    return html_path, snapshot_csv_path, pe_snapshot_csv_path, latest_html_path


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
        help="Skip XLSX export and only update the CSV history files.",
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

    pe_raw_df = build_pe_analysis(raw_df, as_of_date)
    pe_display_df = format_pe_analysis_for_display(pe_raw_df)

    html_path, snapshot_csv_path, pe_snapshot_csv_path, latest_html_path = save_daily_reports(
        raw_df=raw_df,
        display_df=display_df,
        pe_raw_df=pe_raw_df,
        pe_display_df=pe_display_df,
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

    pe_history_csv_path, pe_history_xlsx_path = save_pe_history(
        pe_raw_df=pe_raw_df,
        as_of_date=as_of_date,
        generated_at=generated_at,
        data_dir=args.data_dir,
        export_excel=not args.no_excel,
    )

    print(f"Saved daily HTML report:   {html_path}")
    print(f"Saved latest HTML copy:     {latest_html_path}")
    print(f"Saved daily CSV snapshot:   {snapshot_csv_path}")
    print(f"Saved PE CSV snapshot:      {pe_snapshot_csv_path}")
    print(f"Updated history CSV:        {history_csv_path}")
    if history_xlsx_path is not None:
        print(f"Updated history Excel:      {history_xlsx_path}")
    else:
        print("Updated history Excel:      skipped or failed")

    print(f"Updated PE history CSV:     {pe_history_csv_path}")
    if pe_history_xlsx_path is not None:
        print(f"Updated PE history Excel:   {pe_history_xlsx_path}")
    else:
        print("Updated PE history Excel:   skipped or failed")

    if args.open_browser:
        webbrowser.open(html_path.resolve().as_uri())


if __name__ == "__main__":
    main()
