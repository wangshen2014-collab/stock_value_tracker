#!/usr/bin/env python3
"""Stock Value Tracker: daily HTML valuation report plus CSV/XLSX history."""
from __future__ import annotations

import argparse
import html
import math
import os
import shutil
import sys
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yfinance as yf

DEFAULT_TICKERS = ["GOOG"]
PE_WINDOWS = [90, 180]
MIN_PE_OBSERVATIONS = 20
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]

DISPLAY_COLUMNS = ["Ticker", "Company", "TTM PE", "Forward PE", "PEG", "PS", "EP", "Forward EP", "ERP"]
RAW_COLUMNS = [
    "Ticker", "Company", "Price", "Market Cap", "TTM EPS", "Forward EPS", "TTM PE",
    "Forward PE", "PEG", "PS", "EP", "Forward EP", "10Y Yield", "ERP",
]
HISTORY_COLUMNS = ["Date", "Generated At"] + RAW_COLUMNS

PE_ANALYSIS_RAW_COLUMNS = [
    "Ticker", "Company", "Status", "Method", "Data Quality", "Current Price", "Current TTM EPS",
    "Current TTM PE", "Historical EPS Reports Used",
]
for w in PE_WINDOWS:
    PE_ANALYSIS_RAW_COLUMNS.extend([
        f"PE_{w}D_Count", f"PE_{w}D_Min", f"PE_{w}D_Max", f"PE_{w}D_Mean", f"PE_{w}D_Median",
        f"PE_{w}D_Std", f"PE_{w}D_P10", f"PE_{w}D_P90", f"PE_{w}D_Current_ZScore",
        f"PE_{w}D_Current_Percentile", f"Value_{w}D_Min", f"Value_{w}D_Max", f"Value_{w}D_Mean",
        f"Value_{w}D_Lower_1Std", f"Value_{w}D_Upper_1Std", f"Value_{w}D_P10", f"Value_{w}D_P90",
    ])
PE_ANALYSIS_HISTORY_COLUMNS = ["Date", "Generated At"] + PE_ANALYSIS_RAW_COLUMNS
PE_DISPLAY_COLUMNS = [
    "Ticker", "Method", "Current PE", "EPS Used", "90D PE Range", "90D PE Std", "90D PE Z",
    "90D Value Range", "90D Normal Value", "180D PE Range", "180D PE Std", "180D PE Z",
    "180D Value Range", "180D Normal Value", "Status",
]


class RunLogger:
    def __init__(self, verbose: bool = True) -> None:
        self.verbose = verbose
        self.started_at = datetime.now()
        self.errors: list[tuple[str, str]] = []

    def _emit(self, level: str, msg: str) -> None:
        if self.verbose or level in {"ERROR", "WARN"}:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] [{level:<5}] {msg}", flush=True)

    def step(self, msg: str) -> None:
        self._emit("STEP", msg)

    def info(self, msg: str) -> None:
        self._emit("INFO", msg)

    def warn(self, msg: str) -> None:
        self._emit("WARN", msg)

    def error(self, context: str, exc: Exception | str) -> None:
        text = str(exc)
        self.errors.append((context, text))
        self._emit("ERROR", f"{context}: {text}")

    def summary(self) -> None:
        elapsed = (datetime.now() - self.started_at).total_seconds()
        print("\n" + "=" * 72)
        print("Run Summary")
        print("=" * 72)
        print(f"Elapsed: {elapsed:.1f}s")
        if not self.errors:
            print("Errors: 0")
        else:
            print(f"Errors: {len(self.errors)}")
            for i, (ctx, text) in enumerate(self.errors, start=1):
                print(f"  {i}. {ctx}: {text}")
        print("=" * 72)


LOGGER = RunLogger(verbose=True)


def safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        x = float(v)
        return None if math.isnan(x) or math.isinf(x) else x
    except Exception:
        return None


def is_missing(x: Any) -> bool:
    return x is None or pd.isna(x)


def fmt_num(x: Any, digits: int = 2) -> str:
    x = safe_float(x)
    return "N/A" if is_missing(x) else f"{x:,.{digits}f}"


def fmt_pct(x: Any, digits: int = 2) -> str:
    x = safe_float(x)
    return "N/A" if is_missing(x) else f"{x * 100:.{digits}f}%"


def fmt_money(x: Any, digits: int = 2) -> str:
    x = safe_float(x)
    return "N/A" if is_missing(x) else f"${x:,.{digits}f}"


def fmt_range(low: Any, high: Any, digits: int = 2, money: bool = False) -> str:
    lo, hi = safe_float(low), safe_float(high)
    if is_missing(lo) or is_missing(hi):
        return "N/A"
    return f"{fmt_money(lo, digits)} - {fmt_money(hi, digits)}" if money else f"{fmt_num(lo, digits)} - {fmt_num(hi, digits)}"


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen, result = set(), []
    for item in items:
        ticker = item.upper().strip()
        if ticker and ticker not in seen:
            seen.add(ticker)
            result.append(ticker)
    return result


def normalize_date_series(series: pd.Series) -> pd.Series:
    """Return timezone-free pandas datetime64[ns] normalized to date midnight."""
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    parsed = parsed.dt.tz_convert(None).dt.normalize()
    return parsed.astype("datetime64[ns]")


def parse_dt(value: Any) -> pd.Timestamp | None:
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(parsed):
            return None
        return pd.Timestamp(parsed.tz_convert(None).normalize())
    except Exception:
        return None


def get_last_price(ticker: yf.Ticker, info: dict[str, Any]) -> float | None:
    for k in ["currentPrice", "regularMarketPrice", "previousClose"]:
        p = safe_float(info.get(k))
        if p:
            return p
    try:
        p = safe_float(ticker.fast_info.get("last_price"))
        if p:
            return p
    except Exception:
        pass
    try:
        h = ticker.history(period="5d", auto_adjust=False)
        if not h.empty:
            return safe_float(h["Close"].dropna().iloc[-1])
    except Exception:
        pass
    return None


def get_ten_year_yield() -> float | None:
    LOGGER.step("Fetching 10Y Treasury yield from ^TNX")
    try:
        h = yf.Ticker("^TNX").history(period="10d", auto_adjust=False)
        raw = safe_float(h["Close"].dropna().iloc[-1]) if not h.empty else None
        if raw is None:
            LOGGER.warn("10Y Treasury yield unavailable")
            return None
        if raw > 20:
            y = raw / 1000.0
        elif raw > 1:
            y = raw / 100.0
        else:
            y = raw
        LOGGER.info(f"10Y Treasury yield: {fmt_pct(y)}")
        return y
    except Exception as e:
        LOGGER.error("Fetch 10Y Treasury yield", e)
        return None


def collect_one_stock(symbol: str, ten_year_yield: float | None) -> dict[str, Any]:
    LOGGER.step(f"Fetching current valuation snapshot for {symbol}")
    t = yf.Ticker(symbol)
    try:
        info = t.info or {}
    except Exception as e:
        LOGGER.error(f"{symbol} yfinance info", e)
        info = {}
    price = get_last_price(t, info)
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
    ep = trailing_eps / price if price and trailing_eps and price > 0 else (1 / ttm_pe if ttm_pe and ttm_pe > 0 else None)
    forward_ep = forward_eps / price if price and forward_eps and price > 0 else (1 / forward_pe if forward_pe and forward_pe > 0 else None)
    erp = forward_ep - ten_year_yield if forward_ep is not None and ten_year_yield is not None else None
    LOGGER.info(f"{symbol}: price={fmt_money(price)}, TTM EPS={fmt_num(trailing_eps)}, TTM PE={fmt_num(ttm_pe)}, Forward PE={fmt_num(forward_pe)}")
    return {
        "Ticker": symbol,
        "Company": info.get("shortName") or info.get("longName") or "N/A",
        "Price": price,
        "Market Cap": safe_float(info.get("marketCap")),
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
    LOGGER.step(f"Building main valuation report for {len(tickers)} ticker(s): {', '.join(tickers)}")
    ten_year_yield = get_ten_year_yield()
    rows = []
    for symbol in tickers:
        try:
            rows.append(collect_one_stock(symbol, ten_year_yield))
        except Exception as e:
            LOGGER.error(f"Build main snapshot for {symbol}", e)
            row = {col: None for col in RAW_COLUMNS}
            row.update({"Ticker": symbol, "Company": f"ERROR: {e}", "10Y Yield": ten_year_yield})
            rows.append(row)
    return pd.DataFrame(rows).reindex(columns=RAW_COLUMNS)


def format_for_display(raw_df: pd.DataFrame) -> pd.DataFrame:
    out = raw_df.copy()
    for c in ["TTM PE", "Forward PE", "PEG", "PS"]:
        out[c] = out[c].apply(lambda x: fmt_num(x, 2))
    for c in ["EP", "Forward EP", "ERP"]:
        out[c] = out[c].apply(lambda x: fmt_pct(x, 2))
    return out[DISPLAY_COLUMNS]


def sec_user_agent() -> str:
    return os.getenv("SEC_USER_AGENT", "stock-value-tracker/1.0 personal-research contact@example.com")


def sec_get_json(url: str) -> Any | None:
    try:
        r = requests.get(url, headers={"User-Agent": sec_user_agent(), "Accept-Encoding": "gzip, deflate"}, timeout=20)
        if r.status_code != 200:
            LOGGER.warn(f"SEC request failed HTTP {r.status_code}: {url}")
            return None
        return r.json()
    except Exception as e:
        LOGGER.error(f"SEC request {url}", e)
        return None


def sec_ticker_to_cik(symbol: str) -> str | None:
    data = sec_get_json(SEC_TICKER_MAP_URL)
    if not data:
        return None
    symbol_u = symbol.upper().replace("-", ".")
    for item in data.values():
        if str(item.get("ticker", "")).upper() == symbol_u:
            try:
                return str(int(item["cik_str"])).zfill(10)
            except Exception:
                return None
    return None


def choose_sec_eps_unit(units: dict[str, Any]) -> list[dict[str, Any]] | None:
    for key, values in (units or {}).items():
        if "share" in str(key).lower() and isinstance(values, list):
            return values
    return None


def quarter_from_record(rec: dict[str, Any]) -> str | None:
    fp = str(rec.get("fp", "")).upper()
    if fp in {"Q1", "Q2", "Q3", "Q4"}:
        return fp
    frame = str(rec.get("frame", "")).upper()
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        if q in frame and "YTD" not in frame:
            return q
    return None


def fiscal_order(fy: int, quarter: str) -> int:
    return fy * 10 + int(str(quarter).replace("Q", ""))


def get_sec_ttm_eps_history(symbol: str) -> pd.DataFrame:
    LOGGER.step(f"{symbol}: attempting SEC point-in-time EPS history")
    cik = sec_ticker_to_cik(symbol)
    if cik is None:
        LOGGER.warn(f"{symbol}: SEC CIK not found")
        return pd.DataFrame(columns=["Report Date", "Point-in-Time TTM EPS"])
    facts = sec_get_json(SEC_COMPANY_FACTS_URL.format(cik=cik))
    us_gaap = ((facts or {}).get("facts") or {}).get("us-gaap") or {}
    records = None
    used_tag = None
    for tag in SEC_EPS_TAGS:
        obj = us_gaap.get(tag)
        if obj:
            records = choose_sec_eps_unit(obj.get("units") or {})
            if records:
                used_tag = tag
                break
    if not records:
        LOGGER.warn(f"{symbol}: SEC EPS tag not available")
        return pd.DataFrame(columns=["Report Date", "Point-in-Time TTM EPS"])

    quarters: dict[tuple[int, str], dict[str, Any]] = {}
    annuals: dict[int, dict[str, Any]] = {}
    for rec in records:
        val = safe_float(rec.get("val"))
        filed, start, end = parse_dt(rec.get("filed")), parse_dt(rec.get("start")), parse_dt(rec.get("end"))
        if val is None or filed is None or end is None:
            continue
        fy = int(rec.get("fy") or end.year)
        fp, form = str(rec.get("fp", "")).upper(), str(rec.get("form", "")).upper()
        duration = int((end - start).days) if start is not None else None
        q = quarter_from_record(rec)
        is_quarter = duration is not None and 60 <= duration <= 140
        is_annual = duration is not None and 300 <= duration <= 430
        if q in {"Q1", "Q2", "Q3", "Q4"} and is_quarter:
            key = (fy, q)
            old = quarters.get(key)
            if old is None or filed >= old["Filed"]:
                quarters[key] = {"FY": fy, "Quarter": q, "Filed": filed, "EPS": val, "Fiscal Order": fiscal_order(fy, q)}
        elif (fp == "FY" or "10-K" in form) and is_annual:
            old = annuals.get(fy)
            if old is None or filed >= old["Filed"]:
                annuals[fy] = {"FY": fy, "Filed": filed, "Annual EPS": val}

    for fy, annual in annuals.items():
        vals = [quarters.get((fy, q), {}).get("EPS") for q in ["Q1", "Q2", "Q3"]]
        if all(v is not None for v in vals) and (fy, "Q4") not in quarters:
            quarters[(fy, "Q4")] = {
                "FY": fy, "Quarter": "Q4", "Filed": annual["Filed"],
                "EPS": annual["Annual EPS"] - sum(vals), "Fiscal Order": fiscal_order(fy, "Q4")
            }

    if not quarters:
        LOGGER.warn(f"{symbol}: SEC EPS records found but no usable quarterly EPS")
        return pd.DataFrame(columns=["Report Date", "Point-in-Time TTM EPS"])
    qdf = pd.DataFrame(list(quarters.values())).sort_values(["Filed", "Fiscal Order"])
    rows = []
    for report_date in sorted(qdf["Filed"].dropna().unique()):
        report_ts = pd.Timestamp(report_date).normalize()
        available = qdf[qdf["Filed"] <= report_ts].sort_values("Fiscal Order")
        latest_four = available.tail(4)
        if len(latest_four) >= 4:
            rows.append({
                "Report Date": report_ts,
                "Point-in-Time TTM EPS": safe_float(latest_four["EPS"].sum()),
                "EPS Reports Used": int(len(available)),
                "EPS Source": f"SEC Company Facts {used_tag}",
            })
    if not rows:
        LOGGER.warn(f"{symbol}: SEC did not produce enough quarters for TTM EPS")
        return pd.DataFrame(columns=["Report Date", "Point-in-Time TTM EPS"])
    out = pd.DataFrame(rows).dropna(subset=["Point-in-Time TTM EPS"]).drop_duplicates("Report Date", keep="last").sort_values("Report Date")
    out["Report Date"] = normalize_date_series(out["Report Date"])
    LOGGER.info(f"{symbol}: SEC EPS history rows={len(out)}")
    return out


def get_yfinance_ttm_eps_history(ticker: yf.Ticker, symbol: str) -> pd.DataFrame:
    LOGGER.step(f"{symbol}: attempting Yahoo earnings-date EPS history")
    try:
        earnings = ticker.get_earnings_dates(limit=32)
    except Exception as e:
        LOGGER.error(f"{symbol} Yahoo earnings dates", e)
        earnings = None
    if earnings is None or earnings.empty:
        LOGGER.warn(f"{symbol}: Yahoo earnings dates unavailable")
        return pd.DataFrame(columns=["Report Date", "Point-in-Time TTM EPS"])
    df = earnings.reset_index()
    eps_col = next((c for c in df.columns if "eps actual" in str(c).lower() or "reported eps" in str(c).lower()), None)
    if eps_col is None:
        LOGGER.warn(f"{symbol}: Yahoo earnings dates missing actual EPS column")
        return pd.DataFrame(columns=["Report Date", "Point-in-Time TTM EPS"])
    out = pd.DataFrame({
        "Report Date": normalize_date_series(df[df.columns[0]]),
        "Quarterly EPS": pd.to_numeric(df[eps_col], errors="coerce"),
    }).dropna().sort_values("Report Date").drop_duplicates("Report Date", keep="last")
    out["Point-in-Time TTM EPS"] = out["Quarterly EPS"].rolling(4).sum()
    out = out.dropna(subset=["Point-in-Time TTM EPS"])
    out["EPS Reports Used"] = range(4, 4 + len(out))
    out["EPS Source"] = "Yahoo earnings dates"
    LOGGER.info(f"{symbol}: Yahoo EPS history rows={len(out)}")
    return out[["Report Date", "Point-in-Time TTM EPS", "EPS Reports Used", "EPS Source"]]


def get_price_history_for_pe(ticker: yf.Ticker, symbol: str) -> pd.DataFrame:
    LOGGER.step(f"{symbol}: fetching 1-year daily close prices")
    try:
        hist = ticker.history(period="1y", auto_adjust=False)
    except Exception as e:
        LOGGER.error(f"{symbol} price history", e)
        hist = pd.DataFrame()
    if hist.empty or "Close" not in hist.columns:
        LOGGER.warn(f"{symbol}: no historical close price data")
        return pd.DataFrame(columns=["Date", "Close"])
    out = hist.reset_index()
    date_col = "Date" if "Date" in out.columns else out.columns[0]
    out["Date"] = normalize_date_series(out[date_col])
    out["Close"] = pd.to_numeric(out["Close"], errors="coerce")
    out = out.dropna(subset=["Date", "Close"]).sort_values("Date")[["Date", "Close"]]
    out["Date"] = normalize_date_series(out["Date"])
    LOGGER.info(f"{symbol}: price history rows={len(out)}, date dtype={out['Date'].dtype}")
    return out


def empty_pe_analysis_row(symbol: str, company: str, status: str) -> dict[str, Any]:
    row = {col: None for col in PE_ANALYSIS_RAW_COLUMNS}
    row.update({"Ticker": symbol, "Company": company, "Status": status, "Method": "Skipped", "Data Quality": "No usable PE history"})
    return row


def merge_prices_with_eps(price_df: pd.DataFrame, eps_df: pd.DataFrame, symbol: str, method_name: str) -> pd.DataFrame:
    if price_df.empty or eps_df.empty:
        return pd.DataFrame(columns=["Date", "Close", "Historical PE"])
    p = price_df.copy()
    e = eps_df.copy()
    p["Date"] = normalize_date_series(p["Date"])
    e["Report Date"] = normalize_date_series(e["Report Date"])
    p = p.sort_values("Date")
    e = e.sort_values("Report Date")
    LOGGER.info(f"{symbol}: merge {method_name}: price Date dtype={p['Date'].dtype}, EPS Report Date dtype={e['Report Date'].dtype}, price rows={len(p)}, EPS rows={len(e)}")
    try:
        merged = pd.merge_asof(
            p,
            e[["Report Date", "Point-in-Time TTM EPS"]],
            left_on="Date",
            right_on="Report Date",
            direction="backward",
        )
    except Exception as e_merge:
        LOGGER.error(f"{symbol} merge_asof {method_name}", e_merge)
        return pd.DataFrame(columns=["Date", "Close", "Historical PE"])
    merged = merged.dropna(subset=["Close", "Point-in-Time TTM EPS"])
    merged = merged[merged["Point-in-Time TTM EPS"] > 0]
    if merged.empty:
        LOGGER.warn(f"{symbol}: merge {method_name} produced no rows with positive TTM EPS")
        return pd.DataFrame(columns=["Date", "Close", "Historical PE"])
    merged["Historical PE"] = merged["Close"] / merged["Point-in-Time TTM EPS"]
    merged = merged.replace([math.inf, -math.inf], pd.NA).dropna(subset=["Historical PE"])
    LOGGER.info(f"{symbol}: merge {method_name} produced PE rows={len(merged)}")
    return merged


def count_recent(pe_df: pd.DataFrame, as_of_ts: pd.Timestamp, window: int = 180) -> int:
    if pe_df.empty:
        return 0
    return int(len(pe_df[(pe_df["Date"] >= as_of_ts - pd.Timedelta(days=window)) & (pe_df["Historical PE"] > 0)]))


def build_historical_pe_dataset(symbol: str, price_df: pd.DataFrame, ticker: yf.Ticker, current_ttm_eps: float, as_of_ts: pd.Timestamp) -> tuple[pd.DataFrame, str, str, int]:
    sec_eps = get_sec_ttm_eps_history(symbol)
    if not sec_eps.empty:
        sec_pe = merge_prices_with_eps(price_df, sec_eps, symbol, "SEC point-in-time")
        recent_count = count_recent(sec_pe, as_of_ts)
        LOGGER.info(f"{symbol}: SEC recent PE observations={recent_count}")
        if recent_count >= MIN_PE_OBSERVATIONS:
            used = int(safe_float(sec_eps.get("EPS Reports Used", pd.Series([len(sec_eps)])).dropna().iloc[-1]) or len(sec_eps))
            return sec_pe, "SEC point-in-time", "High", used

    yahoo_eps = get_yfinance_ttm_eps_history(ticker, symbol)
    if not yahoo_eps.empty:
        yahoo_pe = merge_prices_with_eps(price_df, yahoo_eps, symbol, "Yahoo point-in-time")
        recent_count = count_recent(yahoo_pe, as_of_ts)
        LOGGER.info(f"{symbol}: Yahoo recent PE observations={recent_count}")
        if recent_count >= MIN_PE_OBSERVATIONS:
            used = int(safe_float(yahoo_eps.get("EPS Reports Used", pd.Series([len(yahoo_eps)])).dropna().iloc[-1]) or len(yahoo_eps))
            return yahoo_pe, "Yahoo point-in-time", "Medium", used

    LOGGER.warn(f"{symbol}: point-in-time EPS unavailable or insufficient; using Current EPS fallback")
    fallback = price_df.copy()
    fallback["Point-in-Time TTM EPS"] = current_ttm_eps
    fallback["Historical PE"] = fallback["Close"] / current_ttm_eps
    fallback = fallback.replace([math.inf, -math.inf], pd.NA).dropna(subset=["Historical PE"])
    return fallback, "Current EPS fallback", "Low", 0


def add_window_stats(row: dict[str, Any], window: int, pe_series: pd.Series, current_pe: float | None, current_ttm_eps: float | None) -> None:
    pfx, vpfx = f"PE_{window}D", f"Value_{window}D"
    pe = pe_series.dropna()
    pe = pe[pe > 0]
    count = int(len(pe))
    row[f"{pfx}_Count"] = count
    if count < MIN_PE_OBSERVATIONS:
        return
    vals = {
        "Min": pe.min(), "Max": pe.max(), "Mean": pe.mean(), "Median": pe.median(),
        "Std": pe.std(ddof=1), "P10": pe.quantile(0.10), "P90": pe.quantile(0.90),
    }
    for k, v in vals.items():
        row[f"{pfx}_{k}"] = safe_float(v)
    if current_pe is not None and vals["Std"] and vals["Std"] > 0:
        row[f"{pfx}_Current_ZScore"] = (current_pe - vals["Mean"]) / vals["Std"]
    if current_pe is not None:
        row[f"{pfx}_Current_Percentile"] = float((pe <= current_pe).sum() / count)
    if current_ttm_eps is not None and current_ttm_eps > 0:
        for k in ["Min", "Max", "Mean", "P10", "P90"]:
            row[f"{vpfx}_{k}"] = safe_float(vals[k] * current_ttm_eps)
        row[f"{vpfx}_Lower_1Std"] = max(0.0, (vals["Mean"] - vals["Std"]) * current_ttm_eps)
        row[f"{vpfx}_Upper_1Std"] = (vals["Mean"] + vals["Std"]) * current_ttm_eps


def collect_one_pe_analysis(symbol: str, base_row: pd.Series, as_of_date: str) -> dict[str, Any]:
    LOGGER.step(f"{symbol}: building PE volatility analysis")
    row = empty_pe_analysis_row(symbol, str(base_row.get("Company", "N/A")), "OK")
    current_price = safe_float(base_row.get("Price"))
    current_ttm_eps = safe_float(base_row.get("TTM EPS"))
    current_pe = safe_float(base_row.get("TTM PE"))
    if current_ttm_eps is None and current_price and current_pe and current_pe > 0:
        current_ttm_eps = current_price / current_pe
    if current_pe is None and current_price and current_ttm_eps and current_ttm_eps > 0:
        current_pe = current_price / current_ttm_eps
    row.update({"Current Price": current_price, "Current TTM EPS": current_ttm_eps, "Current TTM PE": current_pe})
    if current_ttm_eps is None or current_ttm_eps <= 0:
        row["Status"] = "No positive current TTM EPS; PE analysis skipped"
        LOGGER.warn(f"{symbol}: {row['Status']}")
        return row
    if current_pe is None or current_pe <= 0:
        row["Status"] = "No positive current PE; PE analysis skipped"
        LOGGER.warn(f"{symbol}: {row['Status']}")
        return row
    ticker = yf.Ticker(symbol)
    price_df = get_price_history_for_pe(ticker, symbol)
    if price_df.empty:
        row["Status"] = "No historical close price data from yfinance"
        LOGGER.warn(f"{symbol}: {row['Status']}")
        return row
    as_of_ts = pd.to_datetime(as_of_date, errors="coerce")
    as_of_ts = pd.Timestamp.today().normalize() if pd.isna(as_of_ts) else pd.Timestamp(as_of_ts).normalize()
    pe_df, method, quality, used = build_historical_pe_dataset(symbol, price_df, ticker, current_ttm_eps, as_of_ts)
    row.update({
        "Method": method,
        "Data Quality": quality,
        "Historical EPS Reports Used": used,
        "Status": "OK" if method != "Current EPS fallback" else "OK - fallback used",
    })
    if pe_df.empty:
        row["Status"] = "No usable PE observations"
        LOGGER.warn(f"{symbol}: {row['Status']}")
        return row
    for w in PE_WINDOWS:
        window_df = pe_df[pe_df["Date"] >= as_of_ts - pd.Timedelta(days=w)]
        add_window_stats(row, w, window_df["Historical PE"], current_pe, current_ttm_eps)
        LOGGER.info(f"{symbol}: {w}D PE observations={row.get(f'PE_{w}D_Count')}, PE range={fmt_range(row.get(f'PE_{w}D_Min'), row.get(f'PE_{w}D_Max'))}")
    if max([safe_float(row.get(f"PE_{w}D_Count")) or 0 for w in PE_WINDOWS]) < MIN_PE_OBSERVATIONS:
        row["Status"] = "Not enough PE observations in requested windows"
        LOGGER.warn(f"{symbol}: {row['Status']}")
    return row


def build_pe_analysis(raw_df: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    LOGGER.step("Building PE volatility table")
    rows = []
    for _, base_row in raw_df.iterrows():
        symbol = str(base_row.get("Ticker", "")).upper().strip()
        if not symbol:
            continue
        try:
            rows.append(collect_one_pe_analysis(symbol, base_row, as_of_date))
        except Exception as e:
            LOGGER.error(f"PE analysis for {symbol}", e)
            if LOGGER.verbose:
                traceback.print_exc()
            rows.append(empty_pe_analysis_row(symbol, str(base_row.get("Company", "N/A")), f"ERROR: {e}"))
    return pd.DataFrame(rows).reindex(columns=PE_ANALYSIS_RAW_COLUMNS) if rows else pd.DataFrame(columns=PE_ANALYSIS_RAW_COLUMNS)


def format_pe_analysis_for_display(pe_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in pe_df.iterrows():
        rows.append({
            "Ticker": r.get("Ticker"), "Method": r.get("Method"), "Current PE": fmt_num(r.get("Current TTM PE"), 2), "EPS Used": fmt_num(r.get("Current TTM EPS"), 2),
            "90D PE Range": fmt_range(r.get("PE_90D_Min"), r.get("PE_90D_Max"), 2), "90D PE Std": fmt_num(r.get("PE_90D_Std"), 2), "90D PE Z": fmt_num(r.get("PE_90D_Current_ZScore"), 2),
            "90D Value Range": fmt_range(r.get("Value_90D_Min"), r.get("Value_90D_Max"), 2, True), "90D Normal Value": fmt_range(r.get("Value_90D_P10"), r.get("Value_90D_P90"), 2, True),
            "180D PE Range": fmt_range(r.get("PE_180D_Min"), r.get("PE_180D_Max"), 2), "180D PE Std": fmt_num(r.get("PE_180D_Std"), 2), "180D PE Z": fmt_num(r.get("PE_180D_Current_ZScore"), 2),
            "180D Value Range": fmt_range(r.get("Value_180D_Min"), r.get("Value_180D_Max"), 2, True), "180D Normal Value": fmt_range(r.get("Value_180D_P10"), r.get("Value_180D_P90"), 2, True), "Status": r.get("Status"),
        })
    return pd.DataFrame(rows).reindex(columns=PE_DISPLAY_COLUMNS)


def metric_class(column: str, raw_value: float | None) -> str:
    if raw_value is None or pd.isna(raw_value):
        return "neutral"
    if column == "ERP":
        return "good" if raw_value >= 0.03 else ("okay" if raw_value >= 0.00 else "bad")
    if column in ["Forward EP", "EP"]:
        return "good" if raw_value >= 0.06 else ("okay" if raw_value >= 0.04 else "bad")
    if column == "PEG":
        return "good" if raw_value <= 1.0 else ("okay" if raw_value <= 2.0 else "bad")
    return "neutral"


def zscore_class(x: float | None) -> str:
    if x is None or pd.isna(x):
        return "neutral"
    return "good" if x <= -1.0 else ("okay" if x <= 1.0 else "bad")


def method_class(method: str) -> str:
    return "good" if method == "SEC point-in-time" else ("okay" if method == "Yahoo point-in-time" else ("neutral" if method == "Current EPS fallback" else "bad"))


def html_cell(column: str, display_value: str, raw_value: Any) -> str:
    if column == "Ticker":
        return f'<td class="ticker">{html.escape(display_value)}</td>'
    if column == "Company":
        return f'<td class="company">{html.escape(display_value)}</td>'
    cls = metric_class(column, safe_float(raw_value))
    return f'<td><span class="pill {cls}">{html.escape(display_value)}</span></td>'


def pe_html_cell(column: str, display_value: str, raw_row: pd.Series) -> str:
    if column == "Ticker":
        return f'<td class="ticker">{html.escape(display_value)}</td>'
    if column == "Method":
        return f'<td><span class="pill {method_class(display_value)}">{html.escape(display_value)}</span></td>'
    if column == "Status":
        cls = "good" if display_value == "OK" else ("okay" if "fallback" in display_value.lower() else "bad")
        return f'<td><span class="pill {cls}">{html.escape(display_value)}</span></td>'
    if column == "90D PE Z":
        cls = zscore_class(safe_float(raw_row.get("PE_90D_Current_ZScore")))
        return f'<td><span class="pill {cls}">{html.escape(display_value)}</span></td>'
    if column == "180D PE Z":
        cls = zscore_class(safe_float(raw_row.get("PE_180D_Current_ZScore")))
        return f'<td><span class="pill {cls}">{html.escape(display_value)}</span></td>'
    return f'<td>{html.escape(display_value)}</td>'


def build_table_html(columns: list[str], rows: list[str], extra_class: str = "") -> str:
    header = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    return f'<div class="table-wrap {extra_class}"><table><thead><tr>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def build_main_table_html(raw_df: pd.DataFrame, display_df: pd.DataFrame) -> str:
    rows = []
    for idx, d in display_df.iterrows():
        r = raw_df.iloc[idx]
        rows.append("<tr>" + "".join(html_cell(c, str(d[c]), r[c]) for c in DISPLAY_COLUMNS) + "</tr>")
    return build_table_html(DISPLAY_COLUMNS, rows)


def build_pe_table_html(pe_raw_df: pd.DataFrame, pe_display_df: pd.DataFrame) -> str:
    rows = []
    for idx, d in pe_display_df.iterrows():
        r = pe_raw_df.iloc[idx]
        rows.append("<tr>" + "".join(pe_html_cell(c, str(d[c]), r) for c in PE_DISPLAY_COLUMNS) + "</tr>")
    return build_table_html(PE_DISPLAY_COLUMNS, rows, "pe-table-wrap")


def generate_html_report(raw_df: pd.DataFrame, display_df: pd.DataFrame, pe_raw_df: pd.DataFrame, pe_display_df: pd.DataFrame, tickers: list[str], as_of_date: str, generated_at: str) -> str:
    ten_year_yield = safe_float(raw_df["10Y Yield"].iloc[0]) if not raw_df.empty else None
    ticker_badges = " ".join(f'<span class="ticker-badge">{html.escape(t)}</span>' for t in tickers)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Stock Valuation Report - {as_of_date}</title><meta name="viewport" content="width=device-width, initial-scale=1"><style>
:root{{--bg:#0f172a;--card:#111827;--text:#e5e7eb;--muted:#9ca3af;--border:#374151;--good-bg:#064e3b;--good-text:#a7f3d0;--okay-bg:#78350f;--okay-text:#fde68a;--bad-bg:#7f1d1d;--bad-text:#fecaca;--neutral-bg:#374151;--neutral-text:#e5e7eb}}*{{box-sizing:border-box}}body{{margin:0;padding:32px;background:linear-gradient(135deg,#020617,#111827);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}.container{{max-width:1400px;margin:0 auto}}h1{{margin:0 0 8px;font-size:32px;letter-spacing:-.03em}}h2{{margin:30px 0 12px;font-size:20px}}.subtitle,.section-note{{color:var(--muted);font-size:14px;line-height:1.6}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:24px 0}}.card{{background:rgba(17,24,39,.88);border:1px solid var(--border);border-radius:16px;padding:18px;box-shadow:0 20px 40px rgba(0,0,0,.25)}}.card-label{{color:var(--muted);font-size:13px;margin-bottom:8px}}.card-value{{font-size:24px;font-weight:700}}.ticker-badges{{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}}.ticker-badge{{display:inline-block;padding:6px 10px;border-radius:999px;background:#1e293b;color:#bfdbfe;border:1px solid #334155;font-size:13px;font-weight:600}}.table-wrap{{overflow-x:auto;background:rgba(17,24,39,.88);border:1px solid var(--border);border-radius:16px;box-shadow:0 20px 40px rgba(0,0,0,.25)}}table{{width:100%;border-collapse:collapse;min-width:860px}}.pe-table-wrap table{{min-width:1450px}}th{{text-align:left;color:#cbd5e1;font-size:13px;letter-spacing:.03em;text-transform:uppercase;background:#020617;padding:14px 16px;border-bottom:1px solid var(--border)}}td{{padding:14px 16px;border-bottom:1px solid rgba(55,65,81,.7);font-size:14px;white-space:nowrap}}tr:hover{{background:rgba(30,41,59,.7)}}.ticker{{font-weight:800;color:#93c5fd}}.company{{color:#d1d5db;min-width:220px}}.pill{{display:inline-block;min-width:72px;text-align:right;padding:5px 9px;border-radius:999px;font-variant-numeric:tabular-nums;font-weight:650}}.good{{background:var(--good-bg);color:var(--good-text)}}.okay{{background:var(--okay-bg);color:var(--okay-text)}}.bad{{background:var(--bad-bg);color:var(--bad-text)}}.neutral{{background:var(--neutral-bg);color:var(--neutral-text)}}.notes{{margin-top:24px;color:var(--muted);font-size:14px;line-height:1.6}}.notes code,.section-note code{{color:#dbeafe;background:#1e293b;padding:2px 6px;border-radius:6px}}
</style></head><body><div class="container"><h1>Stock Valuation Report</h1><div class="subtitle">As of {html.escape(as_of_date)} · Generated at {html.escape(generated_at)}</div><div class="cards"><div class="card"><div class="card-label">Tracked Stocks</div><div class="card-value">{len(tickers)}</div><div class="ticker-badges">{ticker_badges}</div></div><div class="card"><div class="card-label">10Y Treasury Yield</div><div class="card-value">{fmt_pct(ten_year_yield)}</div></div><div class="card"><div class="card-label">ERP Formula</div><div class="card-value" style="font-size:18px">Forward EP - 10Y Yield</div></div></div><h2>Current Valuation Snapshot</h2>{build_main_table_html(raw_df, display_df)}<h2>PE Volatility & Valuation Range</h2><div class="section-note">Method priority: <code>SEC point-in-time</code> first, then <code>Yahoo point-in-time</code>, then <code>Current EPS fallback</code>. Value ranges translate PE ranges into price using today's TTM EPS.</div>{build_pe_table_html(pe_raw_df, pe_display_df)}<div class="notes"><p><strong>Formula Notes</strong></p><p><code>PE Z</code> = (Current PE - historical PE mean) / historical PE standard deviation.</p><p><code>Value Range</code> = historical PE min/max multiplied by current TTM EPS.</p><p><code>Normal Value</code> = historical PE P10/P90 multiplied by current TTM EPS. It is usually more stable than min/max.</p><p><code>SEC point-in-time</code> reconstructs historical PE as daily close divided by then-known TTM EPS using SEC filed dates. <code>Current EPS fallback</code> is less rigorous, but keeps the table useful when point-in-time EPS data is unavailable.</p><p>Green / yellow / red colors are only visual scanning aids, not buy or sell signals.</p></div></div></body></html>'''


def merge_and_dedupe_history(today_df: pd.DataFrame, history_path: Path, columns: list[str]) -> pd.DataFrame:
    combined = pd.concat([pd.read_csv(history_path), today_df], ignore_index=True) if history_path.exists() else today_df
    combined = combined.reindex(columns=columns)
    combined["Date"] = combined["Date"].astype(str)
    combined["Ticker"] = combined["Ticker"].astype(str)
    return combined.drop_duplicates(["Date", "Ticker"], keep="last").sort_values(["Date", "Ticker"]).reset_index(drop=True)


def save_history(raw_df: pd.DataFrame, as_of_date: str, generated_at: str, data_dir: str, export_excel: bool = True) -> tuple[Path, Path | None]:
    LOGGER.step("Saving main valuation history")
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    csv_path, xlsx_path = Path(data_dir) / "valuation_history.csv", Path(data_dir) / "valuation_history.xlsx"
    today = raw_df.copy()
    today.insert(0, "Generated At", generated_at)
    today.insert(0, "Date", as_of_date)
    today = today.reindex(columns=HISTORY_COLUMNS)
    combined = merge_and_dedupe_history(today, csv_path, HISTORY_COLUMNS)
    combined.to_csv(csv_path, index=False)
    if not export_excel:
        return csv_path, None
    try:
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            combined.to_excel(writer, sheet_name="History", index=False)
            today.to_excel(writer, sheet_name="Latest", index=False)
        return csv_path, xlsx_path
    except Exception as e:
        LOGGER.error("Main Excel export", e)
        return csv_path, None


def save_pe_history(pe_raw_df: pd.DataFrame, as_of_date: str, generated_at: str, data_dir: str, export_excel: bool = True) -> tuple[Path, Path | None]:
    LOGGER.step("Saving PE valuation history")
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    csv_path, xlsx_path = Path(data_dir) / "pe_valuation_history.csv", Path(data_dir) / "pe_valuation_history.xlsx"
    today = pe_raw_df.copy()
    today.insert(0, "Generated At", generated_at)
    today.insert(0, "Date", as_of_date)
    today = today.reindex(columns=PE_ANALYSIS_HISTORY_COLUMNS)
    combined = merge_and_dedupe_history(today, csv_path, PE_ANALYSIS_HISTORY_COLUMNS)
    combined.to_csv(csv_path, index=False)
    if not export_excel:
        return csv_path, None
    try:
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            combined.to_excel(writer, sheet_name="History", index=False)
            today.to_excel(writer, sheet_name="Latest", index=False)
        return csv_path, xlsx_path
    except Exception as e:
        LOGGER.error("PE Excel export", e)
        return csv_path, None


def save_daily_reports(raw_df: pd.DataFrame, display_df: pd.DataFrame, pe_raw_df: pd.DataFrame, pe_display_df: pd.DataFrame, tickers: list[str], output_dir: str, as_of_date: str, generated_at: str) -> tuple[Path, Path, Path, Path]:
    LOGGER.step("Saving daily HTML and CSV reports")
    daily_dir = Path(output_dir) / as_of_date
    daily_dir.mkdir(parents=True, exist_ok=True)
    html_path = daily_dir / f"stock_report_{as_of_date}.html"
    snap_path = daily_dir / f"stock_snapshot_{as_of_date}.csv"
    pe_snap_path = daily_dir / f"pe_valuation_snapshot_{as_of_date}.csv"
    latest_path = Path(output_dir) / "latest.html"
    raw_df.to_csv(snap_path, index=False)
    pe_raw_df.to_csv(pe_snap_path, index=False)
    html_path.write_text(generate_html_report(raw_df, display_df, pe_raw_df, pe_display_df, tickers, as_of_date, generated_at), encoding="utf-8")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(html_path, latest_path)
    return html_path, snap_path, pe_snap_path, latest_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", nargs="+", default=[])
    p.add_argument("--override", action="store_true")
    p.add_argument("--output-dir", default="reports")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--as-of-date", default=None)
    p.add_argument("--no-excel", action="store_true")
    p.add_argument("--open-browser", action="store_true")
    p.add_argument("--quiet", action="store_true", help="Reduce progress logs. Errors and warnings are still printed.")
    return p.parse_args()


def get_final_ticker_list(args: argparse.Namespace) -> list[str]:
    if args.override:
        if not args.tickers:
            raise ValueError("You used --override but did not provide any --tickers.")
        return dedupe_keep_order(args.tickers)
    return dedupe_keep_order(DEFAULT_TICKERS + args.tickers)


def main() -> None:
    global LOGGER
    args = parse_args()
    LOGGER = RunLogger(verbose=not args.quiet)
    tickers = get_final_ticker_list(args)
    as_of_date = args.as_of_date or datetime.now().strftime("%Y-%m-%d")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        LOGGER.step(f"Starting stock report run. as_of_date={as_of_date}, tickers={', '.join(tickers)}")
        raw_df = build_report(tickers)
        display_df = format_for_display(raw_df)
        pe_raw_df = build_pe_analysis(raw_df, as_of_date)
        pe_display_df = format_pe_analysis_for_display(pe_raw_df)
        html_path, snap, pe_snap, latest = save_daily_reports(raw_df, display_df, pe_raw_df, pe_display_df, tickers, args.output_dir, as_of_date, generated_at)
        hist_csv, hist_xlsx = save_history(raw_df, as_of_date, generated_at, args.data_dir, not args.no_excel)
        pe_csv, pe_xlsx = save_pe_history(pe_raw_df, as_of_date, generated_at, args.data_dir, not args.no_excel)
        LOGGER.step("Output files")
        print(f"Saved daily HTML report:   {html_path}")
        print(f"Saved latest HTML copy:     {latest}")
        print(f"Saved daily CSV snapshot:   {snap}")
        print(f"Saved PE CSV snapshot:      {pe_snap}")
        print(f"Updated history CSV:        {hist_csv}")
        print(f"Updated history Excel:      {hist_xlsx if hist_xlsx else 'skipped or failed'}")
        print(f"Updated PE history CSV:     {pe_csv}")
        print(f"Updated PE history Excel:   {pe_xlsx if pe_xlsx else 'skipped or failed'}")
        if args.open_browser:
            LOGGER.step("Opening HTML report in default browser")
            webbrowser.open(html_path.resolve().as_uri())
    except Exception as e:
        LOGGER.error("Fatal run failure", e)
        if LOGGER.verbose:
            traceback.print_exc()
        sys.exit(1)
    finally:
        LOGGER.summary()


if __name__ == "__main__":
    main()
