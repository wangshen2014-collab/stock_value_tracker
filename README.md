# Stock Value Tracker / 股票估值追踪器

A small personal research tool that pulls valuation data for a watchlist, generates a daily HTML report, and stores a long-term CSV/XLSX history for future charting and analysis.

一个轻量级个人投资研究工具：自动拉取自选股估值数据，生成每日 HTML 网页报告，并把长期历史数据保存为 CSV / Excel，方便日后画图和分析。

> Disclaimer / 免责声明  
> This project is for personal research only. It is not financial advice. Data is pulled through `yfinance`, an unofficial Yahoo Finance data wrapper, so numbers can be delayed, missing, or occasionally inaccurate. Always verify important figures with official filings, company reports, or your brokerage data before making investment decisions.  
> 本项目仅用于个人研究，不构成投资建议。数据通过 `yfinance` 获取，它是非官方 Yahoo Finance 数据封装，因此数据可能延迟、缺失或偶尔不准确。重要投资决策前，请用公司财报、SEC 文件、券商数据等来源复核。

---

## What it tracks / 追踪指标

The HTML table shows one row per stock:

| Metric | Meaning |
|---|---|
| `TTM PE` | trailing twelve month price-to-earnings ratio |
| `Forward PE` | forward price-to-earnings ratio based on analyst estimates |
| `PEG` | PE divided by expected growth rate |
| `PS` | price-to-sales ratio |
| `EP` | earnings yield = EPS / Price = 1 / PE |
| `Forward EP` | forward earnings yield = Forward EPS / Price = 1 / Forward PE |
| `ERP` | equity risk premium approximation = Forward EP - 10Y Treasury Yield |

中文解释：

| 指标 | 含义 |
|---|---|
| `TTM PE` | 过去 12 个月市盈率 |
| `Forward PE` | 基于分析师预期盈利的前瞻市盈率 |
| `PEG` | PE / 预期增长率 |
| `PS` | 市销率 |
| `EP` | 益本比，EPS / 股价，也约等于 1 / PE |
| `Forward EP` | 前瞻益本比，Forward EPS / 股价，也约等于 1 / Forward PE |
| `ERP` | 简化版股权风险溢价，Forward EP - 10 年期美债收益率 |

`10Y Yield` is shown once in the top card of the HTML report because it is the same for all stocks. It is still saved in the historical CSV/XLSX data for future analysis.

`10Y Yield` 在网页顶部只展示一次，因为它对所有股票都一样；但长期历史 CSV / Excel 里仍然会保存，方便未来分析 ERP、利率变化和估值关系。

---

## Output structure / 输出结构

After running the script, you will get:

```text
reports/
  YYYY-MM-DD/
    stock_report_YYYY-MM-DD.html      # daily webpage report / 当日网页报告
    stock_snapshot_YYYY-MM-DD.csv     # daily raw snapshot / 当日原始快照
  latest.html                         # latest report copy / 最新报告副本

data/
  valuation_history.csv               # long-term history database / 长期历史数据库
  valuation_history.xlsx              # Excel version / Excel 版本
```

Each run updates the same `Date + Ticker` row instead of duplicating it. If you run the script multiple times on the same day, the latest run overwrites that day's values for the same ticker.

如果同一天重复运行，不会重复追加同一只股票，而是用最新数据覆盖同一天同一 ticker 的记录。

---

## Files / 文件说明

```text
stock_report.py                       # main script / 主脚本
requirements.txt                      # Python dependencies / Python 依赖
.github/workflows/daily-report.yml    # optional GitHub Actions daily automation / GitHub Actions 自动运行
README.md                             # this guide / 本说明文档
```

---

# Local setup / 本地运行

## Windows

### 1. Install Python / 安装 Python

Recommended: install Python 3.11 or newer from:

```text
https://www.python.org/downloads/windows/
```

During installation, check:

```text
Add python.exe to PATH
```

If you use Windows Package Manager:

```powershell
winget install Python.Python.3.12
```

Close and reopen PowerShell after installation.

安装后关闭并重新打开 PowerShell。

### 2. Check Python / 检查 Python

```powershell
py --version
```

If this works, use `py -m pip`, not plain `pip`:

```powershell
py -m pip install --upgrade pip setuptools wheel
py -m pip install -r requirements.txt
```

If `py` does not work but `python` works:

```powershell
python --version
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

### 3. Run / 运行

```powershell
py stock_report.py --open-browser
```

Append tickers to the default watchlist:

```powershell
py stock_report.py --tickers AAPL MSFT META NVDA --open-browser
```

Override the default watchlist and only show command-line tickers:

```powershell
py stock_report.py --override --tickers AAPL MSFT --open-browser
```

CSV-only mode, useful if Excel export has issues:

```powershell
py stock_report.py --no-excel --open-browser
```

### Common Windows issue / Windows 常见问题

If you see:

```text
pip : The term 'pip' is not recognized
```

Use:

```powershell
py -m pip install -r requirements.txt
```

instead of:

```powershell
pip install -r requirements.txt
```

---

## macOS

### 1. Check Python / 检查 Python

```bash
python3 --version
```

If Python is missing, install it from:

```text
https://www.python.org/downloads/macos/
```

or with Homebrew:

```bash
brew install python
```

### 2. Create virtual environment / 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies / 安装依赖

```bash
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -r requirements.txt
```

### 4. Run / 运行

```bash
python3 stock_report.py --open-browser
```

Append tickers:

```bash
python3 stock_report.py --tickers AAPL MSFT META NVDA --open-browser
```

Override default tickers:

```bash
python3 stock_report.py --override --tickers AAPL MSFT --open-browser
```

---

## Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -r requirements.txt
python3 stock_report.py --open-browser
```

On a headless server, omit `--open-browser`:

```bash
python3 stock_report.py
```

---

# Changing the watchlist / 修改默认自选股

Open `stock_report.py` and edit:

```python
DEFAULT_TICKERS = [
    "GOOG",
]
```

For example:

```python
DEFAULT_TICKERS = [
    "GOOG",
    "GOOGL",
    "META",
    "MSFT",
    "NVDA",
    "AMZN",
]
```

Command-line tickers are appended by default:

```bash
python3 stock_report.py --tickers AAPL TSLA
```

This will run:

```text
GOOG + AAPL + TSLA
```

Use `--override` to ignore `DEFAULT_TICKERS`:

```bash
python3 stock_report.py --override --tickers AAPL TSLA
```

This will run only:

```text
AAPL + TSLA
```

---

# Free public/cloud platforms / 免费线上平台运行方式

## Option 1: GitHub Actions, best for daily automation / GitHub Actions：最适合每日自动运行

This repository includes:

```text
.github/workflows/daily-report.yml
```

It runs on weekdays after the US market close and commits the updated reports/data back into the repository.

这个仓库已经包含 GitHub Actions 工作流。它会在美股收盘后于工作日自动运行，并把更新后的 report 和 data commit 回仓库。

Manual run:

1. Open your GitHub repository.
2. Go to `Actions`.
3. Select `Daily Stock Valuation Report`.
4. Click `Run workflow`.

手动运行：

1. 打开 GitHub 仓库。
2. 进入 `Actions`。
3. 选择 `Daily Stock Valuation Report`。
4. 点击 `Run workflow`。

Important notes:

- Public repositories can use standard GitHub-hosted runners for free, but storage/artifact limits still matter.
- The workflow commits `reports/`, `data/`, and `docs/index.html` back to the repo.
- If your repository is public, your watchlist and reports are public too.
- If you enable GitHub Pages from the `docs/` folder, `docs/index.html` can become your latest web report page.

注意：

- Public repo 的标准 GitHub-hosted runner 通常免费，但仍要注意存储和 artifact 限制。
- workflow 会把 `reports/`、`data/`、`docs/index.html` commit 回仓库。
- 如果仓库是 public，你的自选股和 report 也是公开的。
- 如果在 GitHub Pages 里选择从 `docs/` 文件夹发布，`docs/index.html` 就可以作为最新网页报告。

## Option 2: GitHub Codespaces / GitHub Codespaces：云端 VS Code

Good for manual cloud runs without installing Python locally.

适合不想在本地装 Python、只想临时手动运行的人。

Steps:

1. Open the repository on GitHub.
2. Click `Code`.
3. Click `Codespaces`.
4. Create a new codespace.
5. In the terminal:

```bash
python -m pip install -r requirements.txt
python stock_report.py
```

Codespaces runs in a Linux container even if your local computer is Windows or macOS.

Codespaces 后端是 Linux 容器，所以即使你本地是 Windows / macOS，命令也按 Linux 环境来跑。

## Option 3: Google Colab / Google Colab：适合临时测试

Colab is useful for manual experiments and charts, but it is not ideal for unattended daily automation because the VM is temporary.

Colab 适合临时测试和画图，但不太适合长期无人值守的每日自动化，因为 Colab VM 会回收。

Basic Colab cells:

```python
!git clone https://github.com/wangshen2014-collab/stock_value_tracker.git
%cd stock_value_tracker
!pip install -r requirements.txt
!python stock_report.py --no-excel
```

To keep outputs, download the `reports/` and `data/` folders, or mount Google Drive.

如果要保留输出，需要下载 `reports/` 和 `data/` 文件夹，或者挂载 Google Drive。

## Option 4: Kaggle Notebooks / Kaggle Notebooks：适合 notebook 研究

Kaggle Notebooks can run Python in the browser and is useful for analysis, but it is not the best place for scheduled daily reports.

Kaggle Notebooks 可以在浏览器里跑 Python，适合做 notebook 分析，但不太适合每日定时自动 report。

Typical steps:

```python
!git clone https://github.com/wangshen2014-collab/stock_value_tracker.git
%cd stock_value_tracker
!pip install -r requirements.txt
!python stock_report.py --no-excel
```

## Option 5: Replit and other online IDEs / Replit 等在线 IDE

These can work for manual runs, but free-tier limits and always-on scheduling rules may change. For reliable daily automation, GitHub Actions is usually the simplest free public option.

这些平台可以手动跑，但免费额度和常驻运行规则经常变化。对这个项目来说，GitHub Actions 通常是最简单的免费 public 自动化方式。

---

# GitHub Pages / 发布最新网页报告

The workflow copies:

```text
reports/latest.html
```

to:

```text
docs/index.html
```

To publish the latest report:

1. Open GitHub repository `Settings`.
2. Go to `Pages`.
3. Source: `Deploy from a branch`.
4. Branch: `main`.
5. Folder: `/docs`.
6. Save.

After GitHub Pages is enabled, the latest report page will update when the workflow commits a new `docs/index.html`.

工作流会把：

```text
reports/latest.html
```

复制到：

```text
docs/index.html
```

启用 GitHub Pages 后，最新 report 就可以变成一个网页。

操作：

1. 打开仓库 `Settings`。
2. 进入 `Pages`。
3. Source 选择 `Deploy from a branch`。
4. Branch 选择 `main`。
5. Folder 选择 `/docs`。
6. 保存。

---

# Scheduling locally / 本地定时运行

## Windows Task Scheduler / Windows 任务计划程序

Program:

```text
py
```

Arguments:

```text
C:\path\to\stock_value_tracker\stock_report.py
```

Start in:

```text
C:\path\to\stock_value_tracker
```

If you want to open the browser during the run:

```text
C:\path\to\stock_value_tracker\stock_report.py --open-browser
```

For scheduled background runs, it is usually better not to use `--open-browser`.

定时后台运行时，通常不建议加 `--open-browser`。

## macOS/Linux cron

Example: run at 2:30 PM on weekdays:

```bash
crontab -e
```

Add:

```cron
30 14 * * 1-5 cd /path/to/stock_value_tracker && /usr/bin/python3 stock_report.py >> stock_report.log 2>&1
```

---

# Data analysis examples / 历史数据分析示例

After several days, you can use `data/valuation_history.csv` for charting.

积累几天数据后，可以用 `data/valuation_history.csv` 画图。

Example:

```python
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("data/valuation_history.csv")
goog = df[df["Ticker"] == "GOOG"].copy()
goog["Date"] = pd.to_datetime(goog["Date"])

plt.plot(goog["Date"], goog["Forward PE"])
plt.title("GOOG Forward PE")
plt.xlabel("Date")
plt.ylabel("Forward PE")
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
```

Possible analysis ideas:

- `Forward PE` time series
- `ERP` time series
- `Forward EP` vs `10Y Yield`
- Compare `PEG` across GOOG, META, MSFT, NVDA
- Build valuation percentile charts after enough history is collected

可以分析：

- `Forward PE` 时间序列
- `ERP` 时间序列
- `Forward EP` 和 `10Y Yield` 对比
- GOOG / META / MSFT / NVDA 的 PEG 对比
- 数据积累足够后，做估值历史分位数

---

# Troubleshooting / 常见问题

## `pip` not recognized on Windows

Use:

```powershell
py -m pip install -r requirements.txt
```

## Excel export fails

Run CSV-only mode:

```bash
python stock_report.py --no-excel
```

CSV is the main long-term database. Excel is only a convenience copy.

CSV 才是主数据库，Excel 只是方便打开查看。

## Some values are `N/A`

Possible reasons:

- Yahoo Finance does not provide that field.
- The company has negative earnings.
- Forward estimates are missing.
- Data source temporarily failed.

常见原因：

- Yahoo Finance 没有该字段。
- 公司盈利为负。
- 缺少 forward analyst estimate。
- 数据源暂时失败。

## GitHub Actions did not run exactly at the scheduled time

GitHub scheduled workflows may not run exactly at the minute specified, especially during high load. This is normal for lightweight daily reporting.

GitHub 定时任务不保证精确到分钟，尤其高峰期可能延迟。这对每日估值 report 一般影响不大。

---

# License / 许可证

MIT License.
