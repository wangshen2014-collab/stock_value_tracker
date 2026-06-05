# Point-in-Time PE Volatility / 严谨版 PE 波动分析

This document explains the second table added to the HTML report: `Point-in-Time PE Volatility & Valuation Range`.

本文解释 HTML report 中新增的第二张表：`Point-in-Time PE Volatility & Valuation Range`。

---

## Goal / 目标

The goal is to estimate how a stock's PE multiple has fluctuated over the last 90 and 180 calendar days, and then translate that PE range back into a price range using the current TTM EPS.

目标是统计股票过去 90 天和 180 天的 PE 波动情况，并把这些 PE 区间乘以当前 TTM EPS，转化成一个对应的股价估值区间。

---

## Rigorous method / 严谨算法口径

The script does **not** simply use today's TTM EPS for all historical days.

Instead, it tries to reconstruct point-in-time historical PE:

```text
Historical PE on a given trading day = that day's close price / then-known TTM EPS
```

The then-known TTM EPS is built from reported quarterly EPS data:

```text
Point-in-time TTM EPS = latest 4 reported quarterly EPS values available as of that date
```

中文：

脚本不是简单地用今天的 TTM EPS 去除以过去每天的股价。

它会尝试重建“当时市场可见”的历史 PE：

```text
某个交易日的历史 PE = 当日收盘价 / 当时已经公布的滚动 TTM EPS
```

其中：

```text
当时已经公布的 TTM EPS = 截至该日期最新 4 个已公布季度 EPS 的合计
```

---

## Important limitation / 重要局限

The implementation relies on `yfinance.get_earnings_dates()` to get reported quarterly EPS and earnings report dates.

This is more rigorous than using today's EPS for all historical dates, but it is still not perfect:

- yfinance may not provide complete EPS history for every ticker.
- Report dates may not perfectly model before-market / after-market announcement timing.
- Some symbols, ETFs, REITs, banks, or negative-earnings companies may not be suitable for PE analysis.
- If EPS is negative or missing, PE volatility is skipped.

中文：

当前实现依赖 `yfinance.get_earnings_dates()` 获取季度 EPS 和财报发布日期。

这比“用当前 EPS 回算过去所有 PE”更严谨，但仍然不是完美的机构级 point-in-time 数据库：

- yfinance 不一定对每只股票都提供完整 EPS 历史。
- 财报发布是在盘前还是盘后，目前没有精确建模。
- ETF、REIT、银行、周期股、亏损公司不一定适合用 PE 分析。
- 如果 EPS 为负或缺失，会跳过 PE 波动分析。

---

## New output files / 新增输出文件

Daily snapshot:

```text
reports/YYYY-MM-DD/pe_valuation_snapshot_YYYY-MM-DD.csv
```

Long-term history:

```text
data/pe_valuation_history.csv
data/pe_valuation_history.xlsx
```

The HTML report also contains a second table below the main valuation snapshot.

HTML report 里也会在主估值表下面新增第二张表。

---

## Main displayed columns / 主要展示字段

| Column | Meaning |
|---|---|
| `Current PE` | current TTM PE |
| `EPS Used` | current TTM EPS used to translate PE ranges into price ranges |
| `90D PE Range` | min/max PE over the last 90 calendar days |
| `90D PE P10-P90` | 10th to 90th percentile PE range, usually more stable than min/max |
| `90D PE Std` | standard deviation of reconstructed PE over 90 days |
| `90D PE Z` | `(Current PE - 90D PE Mean) / 90D PE Std` |
| `90D Value Range` | `90D PE min/max * current TTM EPS` |
| `90D Normal Value` | `90D PE P10/P90 * current TTM EPS` |
| `180D ...` | same metrics using a 180-day window |

中文：

| 字段 | 含义 |
|---|---|
| `Current PE` | 当前 TTM PE |
| `EPS Used` | 用于把 PE 区间换算成股价区间的当前 TTM EPS |
| `90D PE Range` | 过去 90 个自然日内 PE 的最低值 / 最高值 |
| `90D PE P10-P90` | 过去 90 天 PE 的 10% 到 90% 分位区间，通常比 min/max 更稳定 |
| `90D PE Std` | 过去 90 天重建 PE 的标准差 |
| `90D PE Z` | `(当前 PE - 90D PE 均值) / 90D PE 标准差` |
| `90D Value Range` | `90D PE 最小/最大值 * 当前 TTM EPS` |
| `90D Normal Value` | `90D PE P10/P90 * 当前 TTM EPS` |
| `180D ...` | 同样指标，但窗口换成 180 天 |

---

## Interpretation / 如何解读

`PE Z` is a rough valuation-temperature indicator:

```text
PE Z <= -1   current PE is meaningfully below recent history
-1 to +1    current PE is close to recent normal range
PE Z > +1   current PE is meaningfully above recent history
```

中文：

`PE Z` 可以粗略理解为估值温度：

```text
PE Z <= -1   当前 PE 明显低于近期历史
-1 到 +1     当前 PE 接近近期正常区间
PE Z > +1    当前 PE 明显高于近期历史
```

`Normal Value` is often more useful than `Value Range`, because min/max can be distorted by one extreme day.

`Normal Value` 通常比 `Value Range` 更实用，因为 min/max 容易被某一天的极端价格扭曲。

---

## Why this is separated from the main table / 为什么单独放一张表

The main table is designed for fast daily scanning.

PE volatility analysis has many columns and a more complex methodology, so it is intentionally shown as a separate table and saved to separate CSV/XLSX history files.

主表用于快速看每日估值快照。

PE 波动分析字段较多、算法也更复杂，所以单独放成第二张表，并且单独保存到 CSV / Excel 历史文件中。
