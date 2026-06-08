# 中国国债期货数据监控系统 | Bond Futures Data Monitor

<p align="center">
  <a href="#中文"><img src="https://img.shields.io/badge/语言-中文-E84D3D?style=for-the-badge&labelColor=3B3F47" alt="中文"></a>
  &nbsp;
  <a href="#english"><img src="https://img.shields.io/badge/Language-English-2F73C9?style=for-the-badge&labelColor=3B3F47" alt="English"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/数据源-Live%20First-F2C94C?style=for-the-badge" alt="Live first">
  <img src="https://img.shields.io/badge/每日调度-19:01%20北京时间-4CAF50?style=for-the-badge" alt="Daily schedule 19:01 Beijing">
  <img src="https://img.shields.io/badge/存储-SQLite-9B51E0?style=for-the-badge" alt="SQLite">
</p>

---

## 中文

### 项目概览

本项目是一个面向中国国债期货研究的自动化数据监控框架。它每天采集国债期货相关的基本面和另类数据，完成清洗、结构化、规则判断和入库，并生成可解释的 Markdown 日报。

项目目标不是预测价格，而是把“数据采集 → 结构化 → 判断 → 存储 → 报告”这条链路稳定跑通，便于后续扩展到更多数据源、历史回测和可视化。

### 这个项目做了什么

- 每天获取至少 5 类国债期货相关数据
- 默认优先使用 live 数据，必要时回退到样例数据
- 支持 Tushare、AKShare 或本地样例回退
- 对新闻和政策文本做结构化分类
- 基于规则生成偏多 / 偏空 / 中性判断
- 将原始数据、特征和结论写入 SQLite
- 生成当日 Markdown 日报
- 支持本地运行、GitHub Actions 自动调度和会话级本地任务

### 数据源

| 数据类别 | 说明 | 主要来源 |
|---|---|---|
| 国债期货 | 收盘价、日收益率、成交量、持仓量 | AKShare / 样例回退 |
| 国债收益率曲线 | 1Y、2Y、5Y、10Y、30Y | Tushare / 样例回退 |
| 资金利率 | DR001、DR007、R007、SHIBOR O/N、SHIBOR 7D | Tushare / 样例回退 |
| 政策与新闻 | 央行、流动性、宏观、供给、风险偏好 | Tushare 新闻 / 样例回退 |
| 文本结构化信号 | 事件类型、影响方向、置信度、推理链条 | 确定性规则分类器 |

### AI 文本信号层

AI 层只负责把非结构化政策/新闻文本转为固定收益研究信号，不直接预测国债期货价格。

每条文本会被结构化为：

| 字段 | 含义 |
|---|---|
| `event_type` | 事件类型，如货币政策、债券供给、资金流动性等 |
| `summary` | 中文摘要 |
| `bond_impact` | 偏多、偏空或中性 |
| `affected_maturity` | 短端、中段、长端、全曲线或不明确 |
| `related_contracts` | 相关国债期货合约 |
| `confidence` | 1 到 5 的置信度 |
| `reasoning` | 事件到收益率再到国债期货的传导链条 |

当前支持两种后端（共享同一 schema，可无缝切换）：

| 后端 | 触发条件 | 说明 |
|---|---|---|
| Claude LLM（`claude-haiku-4-5-20251001`）| 设置了 `ANTHROPIC_API_KEY` | 真实语义理解，输出 JSON 后做 schema 校验 |
| 规则分类器（`rule-based-text-signal-v2`）| 未设置 API key 或 API 调用失败 | 覆盖 8 种 event_type 的关键词映射，编码固定收益领域知识 |

规则分类器覆盖：货币政策、资金流动性、债券供给、通胀、宏观增长、财政政策、海外利率、风险偏好，以及 `other` 兜底。每种事件类型都进一步区分偏多/偏空/中性三个方向。

### 主要输出

| 输出 | 说明 |
|---|---|
| SQLite 数据库 | `data/bond_futures_monitor.db` |
| 每日日报 | `reports_output/YYYY-MM-DD_daily_report.md` |
| 运行日志 | `run_log` 表 |
| 市场判断 | `偏多` / `偏空` / `中性` |

### 项目结构

```text
bond_futures_monitor/
  collectors/       # 期货、收益率、资金利率、政策新闻采集
  ai/               # 文本结构化信号
  features/         # 每日特征工程
  signals/          # 规则化市场判断
  reports/          # Markdown 日报
  config.py         # 环境变量与路径配置
  database.py       # SQLite 建表、入库、去重、日志
  cli.py            # 命令行入口
tests/              # pytest 测试
reports_output/      # 生成的日报
```

### 数据库

默认使用 SQLite，适合本地研究、自动化任务和快速复现。

核心表：

| 表名 | 用途 |
|---|---|
| `futures_quotes` | 国债期货行情 |
| `bond_yields` | 国债收益率曲线 |
| `funding_rates` | 资金利率 |
| `policy_news` | 政策与新闻文本 |
| `ai_text_signals` | 文本结构化信号 |
| `daily_features` | 每日特征 |
| `daily_market_signals` | 每日规则判断 |
| `run_log` | 运行日志 |

### 运行方式

#### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

#### 2. 配置环境变量

复制 `.env.example` 为 `.env`，按需填写：

```text
DATABASE_PATH=data/bond_futures_monitor.db
REPORTS_OUTPUT_DIR=reports_output
USE_LIVE_DATA=1
TUSHARE_TOKEN=你的TushareToken
ANTHROPIC_API_KEY=你的LLM密钥（可选）
```

说明：
- `USE_LIVE_DATA=1` 是默认值
- 如果没有可用 live 数据源，系统会回退到样例数据
- `ANTHROPIC_API_KEY` 是可选参数，用于启用真实 LLM 文本分析
- 本地 `.env` 不会提交到仓库

#### 3. 初始化数据库

```powershell
python -m bond_futures_monitor.cli init-db
```

#### 4. 运行每日流程

```powershell
python -m bond_futures_monitor.cli run --date 2026-06-08
```

如果不指定日期，GitHub Actions 会默认按"今天（北京时间）"执行。

#### 5. 仅生成日报

```powershell
python -m bond_futures_monitor.cli generate-report --date 2026-06-08
```

### 自动调度

#### GitHub Actions

仓库内置每日定时 workflow：

- 北京时间：19:01
- GitHub cron：`1 11 * * *`
- 数据模式：`USE_LIVE_DATA=1`
- 运行后会生成日报并自动提交到 `main`

需要在 GitHub 仓库配置 Secret：

```text
Name: TUSHARE_TOKEN
Value: 你的 Tushare token
```

#### Windows 本地任务计划程序

也可以在本机注册 Windows Task Scheduler 任务，每天本地时间 19:01 运行：

```powershell
.\scripts\register_windows_task.ps1
```

默认任务名为 `BondFuturesDataMonitorDaily`，任务会调用：

```powershell
.\scripts\run_daily_local.ps1
```

本地运行日志会写入 `logs/daily-monitor-YYYYMMDD-HHMMSS.log`。任务运行时会在项目根目录加载 `.env`，因此本机需要先配置好 `TUSHARE_TOKEN` 等环境变量。

### 判断逻辑

系统会从以下维度做简单规则判断：

- 10Y 收益率变化
- 10Y-2Y 利差
- 30Y-10Y 利差
- DR007 变化
- 国债期货日收益率和成交量变化
- 文本结构化信号

最终输出：

- `偏多`
- `偏空`
- `中性`

并附带：

- 评分拆解
- 特征面板
- 数据源与质量提示
- 核心驱动
- 风险提示

### 报告示例

```text
日期：2026-06-08
综合评分：4.00
市场观点：偏多
```

### 测试

```powershell
pytest
```

覆盖内容包括：
- 数据库初始化与去重
- 默认 live 配置
- 规则评分
- 日报生成

### 交付说明

如果这是作为作业或笔试 project 提交，建议附上：

- README
- 代码目录说明
- 数据源说明
- 运行步骤
- 一页设计说明
- 1～2 张生成日报截图

### 后续可以继续做的事

- 增加更多另类数据源
- 加入历史回测
- 接入仪表盘
- 扩展到 PostgreSQL
- 加入更细的异常检测和告警

---

## English

### Overview

This project is an automated monitoring framework for China Treasury bond futures research. It collects daily fundamental and alternative data, cleans and structures it, applies rule-based judgment, stores everything in SQLite, and generates an explainable Markdown report.

The goal is not to predict prices. The goal is to make the full pipeline reliable and reproducible: data collection → structuring → judgment → storage → reporting.

### What it does

- Collects at least 5 categories of Treasury bond futures related data every day
- Prefers live data by default, with sample fallback when needed
- Supports Tushare, AKShare, and local sample data
- Converts policy/news text into structured signals
- Produces simple bullish / bearish / neutral judgments
- Writes raw data, features, and conclusions into SQLite
- Generates a daily Markdown report
- Supports local runs, GitHub Actions, and a local session task

### Data sources

| Data | Description | Main source |
|---|---|---|
| Treasury bond futures | Close price, daily return, volume, open interest | AKShare / sample fallback |
| Yield curve | 1Y, 2Y, 5Y, 10Y, 30Y yields | Tushare / sample fallback |
| Funding rates | DR001, DR007, R007, SHIBOR O/N, SHIBOR 7D | Tushare / sample fallback |
| Policy & news | PBOC, liquidity, macro, supply, risk appetite | Tushare news / sample fallback |
| Text signals | Event type, impact direction, confidence, reasoning | Deterministic rule-based classifier |

### AI text signal layer

The AI layer converts unstructured policy/news text into structured fixed-income research signals. It does not directly predict futures prices.

Each article is structured into:

| Field | Description |
|---|---|
| `event_type` | Monetary policy, bond supply, funding liquidity, etc. |
| `summary` | Chinese summary |
| `bond_impact` | Bullish, bearish, or neutral |
| `affected_maturity` | Short end, belly, long end, full curve, or unclear |
| `related_contracts` | Related treasury futures contracts |
| `confidence` | 1 to 5 confidence score |
| `reasoning` | Causal chain: event → yield impact → futures implication |

Two backends share the same schema:

| Backend | When | Description |
|---|---|---|
| Claude LLM (`claude-haiku-4-5-20251001`) | `ANTHROPIC_API_KEY` is set | Real semantic understanding, JSON output with schema validation |
| Rule-based classifier (`rule-based-text-signal-v2`) | No API key or API failure | 8 event types via keyword mapping, encoding fixed-income domain knowledge |

The rule-based classifier covers: monetary policy, funding liquidity, bond supply, inflation, macro growth, fiscal policy, overseas rates, risk sentiment, with `other` as fallback. Each event type supports bullish/bearish/neutral sub-classification.

### Outputs

| Output | Description |
|---|---|
| SQLite database | `data/bond_futures_monitor.db` |
| Daily report | `reports_output/YYYY-MM-DD_daily_report.md` |
| Run log | `run_log` table |
| Market view | `bullish` / `bearish` / `neutral` |

### Project layout

```text
bond_futures_monitor/
  collectors/       # futures, yield curve, funding, policy news collectors
  ai/               # text structuring layer
  features/         # daily feature engineering
  signals/          # rule-based market judgment
  reports/          # Markdown reports
  config.py         # environment variables and paths
  database.py       # SQLite schema, inserts, dedupe, logs
  cli.py            # command-line entry point
tests/              # pytest tests
reports_output/      # generated reports
```

### Database

SQLite is the default backend, which keeps the project easy to run locally and easy to reproduce.

Core tables:

| Table | Purpose |
|---|---|
| `futures_quotes` | Treasury bond futures quotes |
| `bond_yields` | Yield curve |
| `funding_rates` | Funding rates |
| `policy_news` | Policy/news text |
| `ai_text_signals` | Structured text signals |
| `daily_features` | Daily features |
| `daily_market_signals` | Rule-based market judgments |
| `run_log` | Run history |

### Quick start

#### 1. Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

#### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in what you need:

```text
DATABASE_PATH=data/bond_futures_monitor.db
REPORTS_OUTPUT_DIR=reports_output
USE_LIVE_DATA=1
TUSHARE_TOKEN=your_tushare_token
ANTHROPIC_API_KEY=your_llm_key（optional）
```

Notes:
- `USE_LIVE_DATA=1` is the default
- If live sources are unavailable, the pipeline falls back to sample data
- `ANTHROPIC_API_KEY` is optional — enables real LLM text analysis when set
- Local `.env` files are not committed to the repository

#### 3. Initialize the database

```powershell
python -m bond_futures_monitor.cli init-db
```

#### 4. Run the daily pipeline

```powershell
python -m bond_futures_monitor.cli run --date 2026-06-08
```

If you omit the date, GitHub Actions resolves it as "today" in Beijing time.

#### 5. Generate a report only

```powershell
python -m bond_futures_monitor.cli generate-report --date 2026-06-08
```

### Scheduling

#### GitHub Actions

The repository includes a daily scheduled workflow:

- Beijing time: 19:01
- GitHub cron: `1 11 * * *`
- Data mode: `USE_LIVE_DATA=1`
- The workflow generates a report and commits it to `main`

You need to configure the following secret in GitHub:

```text
Name: TUSHARE_TOKEN
Value: your Tushare token
```

#### Windows Task Scheduler

You can also register a local Windows scheduled task that runs every day at 19:01 local time:

```powershell
.\scripts\register_windows_task.ps1
```

The default task name is `BondFuturesDataMonitorDaily`. It runs:

```powershell
.\scripts\run_daily_local.ps1
```

Local run logs are written to `logs/daily-monitor-YYYYMMDD-HHMMSS.log`. The task runs from the repository root and loads `.env`, so configure local credentials such as `TUSHARE_TOKEN` first.

### Judgment logic

The rule engine looks at:

- 10Y yield change
- 10Y-2Y spread
- 30Y-10Y spread
- DR007 change
- Futures return and volume change
- Structured text signals

The final output is one of:

- `bullish`
- `bearish`
- `neutral`

The report also includes:

- score breakdown
- feature panel
- data source quality notes
- key drivers
- risk notes

### Report example

```text
Date: 2026-06-08
Total score: 4.00
Market view: bullish
```

### Testing

```powershell
pytest
```

Coverage includes:
- database initialization and deduplication
- default live-data configuration
- rule scoring
- report generation

### Submission notes

If you are submitting this as an assignment or written exam project, include:

- README
- directory overview
- data source description
- run instructions
- one-page design note
- 1–2 screenshots of generated reports

### Possible next steps

- Add more alternative data sources
- Add backtesting
- Add a dashboard
- Migrate to PostgreSQL
- Add stronger anomaly detection and alerting
