# 中国国债期货数据监控系统 | Bond Futures Data Monitor

一个面向中国国债期货研究的自动化数据监控 MVP，整合期货行情、国债收益率曲线、资金利率、政策/新闻文本信号，并生成可解释的每日市场判断。

本项目不是高频交易策略，也不声称直接预测价格。它的目标是构建一套可复现、可扩展、可解释的固定收益数据基础设施：先把数据采集、清洗、入库、文本结构化和规则化判断跑通，再逐步接入更完整的数据源、LLM 与可视化层。

## 中文

### 项目概览

本仓库围绕中国国债期货 `TS`、`TF`、`T`、`TL` 构建日频研究监控流程。系统会收集或回退加载以下数据：

| 模块 | 内容 | MVP 状态 |
|---|---|---|
| 国债期货 | 收盘价、日收益率、成交量、持仓量 | 已支持样例回退数据 |
| 收益率曲线 | 1Y、2Y、5Y、10Y、30Y 国债收益率 | 已支持样例回退数据 |
| 资金利率 | DR001、DR007、R007、SHIBOR O/N、SHIBOR 7D | 已支持样例回退数据 |
| 政策/新闻文本 | 央行、流动性、宏观、债券供给、风险偏好 | 已支持样例回退数据 |
| AI 文本信号 | 文本转结构化固定收益信号 | 已支持确定性 mock 分类器 |
| 规则判断 | 综合评分、市场观点、驱动因素、风险提示 | 已支持 |
| 日报输出 | Markdown 每日监控报告 | 已支持 |

MVP 默认可离线运行。当 AKShare 或其他实时数据源不可用时，系统使用内置样例数据，保证完整管道可以被本地复现和测试。

### 系统架构

```text
数据采集层
  -> SQLite 数据库
  -> AI 文本到信号层
  -> 每日特征工程
  -> 透明规则评分
  -> Markdown 日报
```

核心目录：

```text
bond_futures_monitor/
  collectors/       # 期货、收益率、资金利率、政策新闻采集
  ai/               # mock AI 文本结构化信号
  features/         # 每日特征工程
  signals/          # 规则化市场判断
  reports/          # Markdown 日报
  config.py         # 环境变量与路径配置
  database.py       # SQLite 建表、入库、去重、日志
  cli.py            # 命令行入口
tests/              # pytest 测试
```

### 数据库设计

当前版本使用 SQLite，适合本地研究、GitHub 展示和快速复现。数据库默认路径为：

```text
data/bond_futures_monitor.db
```

核心表：

| 表名 | 用途 |
|---|---|
| `futures_quotes` | 国债期货行情 |
| `bond_yields` | 国债收益率曲线 |
| `funding_rates` | 资金利率 |
| `policy_news` | 政策与新闻文本 |
| `ai_text_signals` | AI 文本结构化信号 |
| `daily_features` | 每日特征 |
| `daily_market_signals` | 每日规则判断 |
| `run_log` | 运行日志 |

SQLite 是 MVP 的默认选择。后续如果需要服务器部署、多人访问或长期任务调度，可以扩展 MySQL 或 PostgreSQL 后端。

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

当前实现为确定性 mock 分类器，因此不需要外部 LLM API key。未来可以在同一 schema 下接入真实 LLM。

### 每日特征与规则评分

系统会生成以下核心特征：

| 特征 | 解释 |
|---|---|
| 10Y 收益率变化 | 识别中长端利率方向 |
| 30Y 收益率变化 | 识别超长端利率方向 |
| 10Y-2Y 利差 | 衡量曲线斜率 |
| 30Y-10Y 利差 | 衡量超长端期限溢价 |
| DR007 变化 | 衡量银行间资金松紧 |
| 国债期货日收益率 | 衡量期货价格动量 |
| 成交量变化 | 衡量交易活跃度 |
| AI 文本情绪均值 | 汇总政策/新闻文本方向 |
| 数据源标签 | 标记 AKShare、Tushare 或 sample fallback 来源 |

规则判断保持透明：

| 条件 | 分数方向 |
|---|---|
| 10Y 收益率明显下行 | 偏多 |
| 10Y 收益率明显上行 | 偏空 |
| 10Y-2Y 利差偏窄 | 小幅偏多 |
| 10Y-2Y 利差偏宽 | 小幅偏空 |
| DR007 下行 | 偏多 |
| DR007 上行 | 偏空 |
| 期货价格上涨且成交活跃度提高 | 偏多 |
| 期货价格下跌且成交活跃度提高 | 偏空 |
| AI 文本信号偏多 | 加分 |
| AI 文本信号偏空 | 减分 |

最终输出 `偏多`、`偏空` 或 `中性` 的每日市场判断，并附带：

- 评分拆解：按利率方向、曲线形态、资金面、期货量价、文本信号拆分分数。
- 特征面板：展示收益率变化、期限利差、资金利率、期货收益、文本情绪等指标。
- 数据源与质量：标记数据来自 AKShare、Tushare 还是 sample fallback。
- 核心驱动：只列出真正触发评分的原因。
- 风险提示：说明缺失数据、曲线风险、fallback 数据和非交易建议边界。

### 安装与运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

如需自定义路径，可复制 `.env.example` 为 `.env`。

初始化数据库：

```powershell
python -m bond_futures_monitor.cli init-db
```

运行完整每日流程：

```powershell
python -m bond_futures_monitor.cli run --date 2026-06-08
```

仅从已有数据库生成日报：

```powershell
python -m bond_futures_monitor.cli generate-report --date 2026-06-08
```

### GitHub Actions 自动日报

仓库已内置 GitHub Actions workflow：

```text
.github/workflows/daily-report.yml
```

自动运行规则：

| 项目 | 设置 |
|---|---|
| 运行时间 | 北京时间每天 19:00 |
| GitHub cron | `0 11 * * *` |
| 数据模式 | `USE_LIVE_DATA=1` |
| 输出文件 | `reports_output/YYYY-MM-DD_daily_report.md` |
| 提交方式 | 由 `github-actions[bot]` 自动 commit 到 `main` |

使用前需要在 GitHub 仓库配置 Secret：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
Name: TUSHARE_TOKEN
Value: 你的 Tushare token
```

也可以在 GitHub Actions 页面手动触发 `Daily Bond Futures Report`，并指定 `run_date`；默认值 `today` 会按北京时间解析。

### 输出示例

运行后会生成：

```text
data/bond_futures_monitor.db
reports_output/2026-06-08_daily_report.md
```

示例市场判断：

```text
日期：2026-06-08
综合评分：4.00
市场观点：偏多
核心驱动：
  - 10Y 国债收益率明显下行，对国债期货形成支撑。
  - DR007 下行，显示资金面边际转松。
  - 期货价格上涨且成交活跃度提高，量价配合偏积极。
```

### 测试

```powershell
pytest
```

测试覆盖数据库初始化、重复插入去重、mock AI 输出 schema、规则评分逻辑和日报生成。

### 后续改进

- 接入真实 LLM API，但保持文本到信号定位，不做黑箱价格预测。
- 扩展 AKShare 与官方/公开数据源覆盖。
- 增加历史文本信号回测与事后解释评估。
- 增加仪表盘可视化。
- 增加每日 19:00 自动调度。
- 增加 RAG 周度固定收益报告生成。
- 增加 MySQL 或 PostgreSQL 后端，支持服务器部署和多人访问。
