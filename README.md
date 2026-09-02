# 中国国债期货真实数据监控 | Bond Futures Real-Data Monitor

<p align="center">
  <a href="#中文"><img src="https://img.shields.io/badge/语言-中文-E84D3D?style=for-the-badge&labelColor=3B3F47" alt="中文"></a>
  &nbsp;
  <a href="#english"><img src="https://img.shields.io/badge/Language-English-2F73C9?style=for-the-badge&labelColor=3B3F47" alt="English"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/数据源-AKShare · Tushare-F2C94C?style=for-the-badge" alt="AKShare + Tushare">
  <img src="https://img.shields.io/badge/调度-GitHub Actions · Cron-4CAF50?style=for-the-badge" alt="Scheduling">
  <img src="https://img.shields.io/badge/数据库-SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite">
</p>

---

## 中文

### 一句话概览

这是一个面向中国国债期货研究的每日真实数据监控项目。项目每天北京时间 19:00 后自动抓取六路真实数据——期货行情、国债收益率曲线、资金利率、央行公开市场操作、政策新闻文本、宏观基本面指标——完成清洗、结构化、入库、特征构造、文本信号提取、规则评分和日报生成。

项目的核心目标不是直接预测国债期货价格，而是搭建一条稳定、可复核、可扩展的数据研究链路：

```text
真实数据采集 -> 数据清洗 -> 结构化入库 -> 特征构造 -> 文本信号 -> 规则判断 -> 每日报告
```

生产流程坚持一个原则：**不使用 sample/mock/fake 数据**。如果真实数据源不可用、覆盖不足或来源标记异常，程序会直接失败，并在运行日志中记录原因。

### 快速导航

| 你想看什么 | 入口 |
|---|---|
| 项目定位与设计思路 | [项目定位](#项目定位) |
| 总体架构与执行流程 | [总体架构](#总体架构) |
| 六路数据源详细字段 | [数据源与字段](#数据源与字段) |
| 数据质量控制 | [真实数据质量控制](#真实数据质量控制) |
| 文本信号与规则评分 | [文本信号层](#文本信号层) |
| 环境配置与命令行 | [环境配置](#环境配置) |
| 自动调度方案 | [自动调度](#自动调度) |
| 工程权衡与边界 | [数据质量与工程权衡](#数据质量与工程权衡) |

---

### 项目定位

国债期货的日常研究通常需要同时关注几个层面：

- 期货自身的价格、成交量和持仓变化。
- 国债收益率曲线的短端、中端、长端变化。
- 银行间资金面和回购利率。
- 央行公开市场操作的投放与回笼节奏。
- 财政、货币政策、债券供给和风险偏好相关信息。
- 新闻文本中隐含的利率债方向性信号。
- LPR、CPI、PPI、PMI 等宏观基本面数据。

这个项目把这些信息放进同一条每日自动化流程中，形成一个轻量但完整的研究底座。它适合作为后续扩展的基础，例如加入更多数据源、更多文本模型、可视化面板、历史回测或策略研究。

### 设计思路

项目设计时遵循四个思路。

第一，数据必须真实。生产代码不再保留样例回退逻辑，真实数据缺失时宁可失败，也不生成看似完整但不可用的报告。

第二，链路必须可追踪。每一类数据都会写入 `data_source` 字段，日报会展示来源，数据库中也保留原始数据、派生特征和最终判断。

第三，判断必须可解释。市场观点不是黑箱输出，而是由收益率变化、资金面变化、期货量价关系和文本信号共同触发。每一项评分都会保留理由。

第四，结构必须便于扩展。采集器、特征层、文本层、评分层、报告层分开组织，未来可以替换单个模块，而不需要重写整条链路。

### 总体架构

```text
bond_futures_monitor/
  collectors/       # 真实数据采集：期货、收益率、资金利率、公开市场操作、政策新闻、宏观指标
  ai/               # 政策/新闻文本结构化，输出固定 schema 的利率债信号
  features/         # 每日特征构造：曲线、资金面、量价、文本情绪
  signals/          # 可解释规则评分：偏多、偏空、中性
  reports/          # Markdown 日报生成
  validation.py     # 真实数据覆盖和来源校验
  database.py       # SQLite 建表、入库、去重、刷新和日志
  cli.py            # 命令行入口
tests/              # pytest 测试
reports_output/     # 生成的每日监控报告
data/               # SQLite 数据库
scripts/            # 本地自动调度脚本
```

每日运行时，`cli.py` 会按下面顺序执行：

1. 解析运行日期，默认使用北京时间当天。
2. 初始化 SQLite 表结构。
3. 清空同一日期的旧原始数据和派生数据，保证重跑是一次完整刷新。
4. 调用各类 collector 抓取真实数据（含宏观指标的最新可得一期）。
5. 执行真实数据覆盖校验。
6. 对政策/新闻文本生成结构化信号。
7. 构造每日特征。
8. 根据规则生成市场判断。
9. 写入数据库并生成 Markdown 日报。

### 数据源与字段

#### 国债期货行情

国债期货行情用于观察期货价格本身的方向、成交活跃度和持仓变化。

| 字段 | 含义 |
|---|---|
| `date` | 运行日期 |
| `contract` | 国债期货品种：`TS`、`TF`、`T`、`TL` |
| `close_price` | 收盘价 |
| `daily_return` | 日收益率 |
| `volume` | 成交量 |
| `open_interest` | 持仓量 |
| `data_source` | 数据来源和查询日期 |

数据优先来自 AKShare 的中金所日行情接口。项目要求覆盖四个国债期货品种：

- `TS`：2 年期国债期货
- `TF`：5 年期国债期货
- `T`：10 年期国债期货
- `TL`：30 年期国债期货

如果中金所日行情接口没有完整返回四个品种，程序会尝试 AKShare 的新浪主力连续合约真实行情。两者都无法满足覆盖要求时，流程失败。

#### 国债收益率曲线

收益率曲线是判断利率债环境的核心数据。项目优先尝试 Tushare `yc_cb`，权限不足时使用 AkShare 的中债收益率曲线公开数据。

| 期限 | 研究含义 |
|---|---|
| `1Y` | 短端利率，对资金面和货币政策预期敏感 |
| `2Y` | 短端到中端过渡，和 `TS`、`TF` 相关 |
| `5Y` | 中段曲线，对 `TF` 更敏感 |
| `10Y` | 长端核心基准，对 `T` 更敏感 |
| `30Y` | 超长端，对 `TL` 和债券供给预期更敏感 |

项目会计算：

- `yield_10y_change`：10Y 收益率相对上一可用日期的变化。
- `yield_30y_change`：30Y 收益率相对上一可用日期的变化。
- `spread_10y_2y`：10Y-2Y 利差，用于观察曲线陡峭或扁平。
- `spread_30y_10y`：30Y-10Y 利差，用于观察超长端期限溢价。

#### 资金利率

资金面影响债券持仓成本和短端利率预期。项目默认通过 AkShare 获取中国外汇交易中心回购定盘利率和公开 Shibor 数据；Tushare 仅作为备用源。

| 指标 | 含义 |
|---|---|
| `DR001` | 银行间存款类机构隔夜质押式回购利率 |
| `DR007` | 银行间存款类机构 7 天质押式回购利率 |
| `R007` | 银行间 7 天质押式回购利率 |
| `SHIBOR_ON` | 隔夜 Shibor |
| `SHIBOR_7D` | 7 天 Shibor |

其中 `DR007` 被用作资金面变化的核心指标：

- `DR007` 下行：资金边际转松，通常对利率债偏友好。
- `DR007` 上行：资金边际收紧，通常对利率债形成压力。

#### 公开市场操作

公开市场操作直接反映央行对银行体系流动性的投放和回收，是连接货币政策、资金面和国债期货定价的重要数据。项目从真实新闻文本中解析央行逆回购相关信息。

| 字段 | 含义 |
|---|---|
| `operation_type` | 操作类型，例如逆回购、买断式逆回购 |
| `tenor_days` | 操作期限，统一折算为天 |
| `operation_amount` | 当日投放金额，单位为亿元 |
| `maturity_amount` | 当日到期金额，单位为亿元 |
| `net_injection_amount` | 净投放金额，投放为正、回笼为负 |
| `source_title` | 解析该记录的原始新闻标题 |
| `data_source` | 数据来源 |

解析逻辑优先识别央行、人民银行、公开市场、逆回购、到期、净投放、净回笼等关键词，并用正则提取金额和期限。由于公开新闻中操作利率字段经常缺失，当前日报不展示该字段。

#### 政策与新闻文本

政策和新闻文本优先来自 AkShare 财联社电报，Tushare `news(src="cls")` 作为备用。项目会过滤全市场噪声，只保留与中国利率债、国债期货、财政货币政策、债券供给和银行间资金面相关的内容；当天没有匹配文本时，该维度按中性处理，不阻断日报。

过滤逻辑分为三层：

1. 保留高相关锚点，例如央行、人民银行、国债、国债期货、利率债、地方债、专项债、特别国债、财政部、国家发改委、银行间、DR007、Shibor、MLF、LPR、降准、降息、货币政策。
2. 识别泛金融噪声，例如 ETF、股票、股份回购、员工持股、个股增持、资金加仓、重大资产重组、公司债务融资工具等。
3. 对含噪声词的文本要求更高的政府债或政策锚点，避免把个股新闻、海外股市新闻或公司融资新闻误判为国债期货相关信息。

这一步的目标不是过滤得越多越好，而是减少"看似金融、实际和国债期货关系很弱"的文本进入结构化报告。

#### 宏观基本面指标

宏观数据决定利率债的中期趋势背景。项目默认从 AkShare 公开源获取五个核心指标，Tushare 作为备用；记录的是**运行日可得的最新一期发布值**，并在 `period` 字段保留数据期：

| 指标 | 来源接口 | 研究含义 |
|---|---|---|
| `LPR_1Y` | `macro_china_lpr` | 1 年期贷款市场报价利率，政策利率锚 |
| `LPR_5Y` | `macro_china_lpr` | 5 年期以上 LPR，与地产和长端更相关 |
| `CPI_YOY` | `macro_china_cpi` | CPI 同比，通胀压力 |
| `PPI_YOY` | `macro_china_ppi` | PPI 同比，工业品价格和名义增长 |
| `PMI_MFG` | `macro_china_pmi` | 制造业 PMI，景气度与荣枯线对比 |

宏观指标按月度或不定期发布，与日频数据天然不同步。项目的处理方式是按运行日落库当时最新值，既保证每日报告有完整宏观背景，也保留了"当时可知"的时点信息，避免未来数据泄漏。

### 数据清洗与结构化

采集到的数据会在进入数据库前做基础清洗：

- 日期统一为 `YYYY-MM-DD`。
- 行情数值统一为浮点数。
- 国债期货品种统一为 `TS`、`TF`、`T`、`TL`。
- 收益率期限统一为 `1Y`、`2Y`、`5Y`、`10Y`、`30Y`。
- 资金利率名称统一为 `DR001`、`DR007`、`R007`、`SHIBOR_ON`、`SHIBOR_7D`。
- 公开市场操作金额统一为亿元人民币。
- 每条数据保留 `data_source`，便于追踪来源。
- 同一日期重跑时会先清空旧数据，再写入新数据，避免旧结果和新结果混在一起。

数据库使用 SQLite，适合本地研究、自动化任务和轻量部署。核心表包括：

| 表名 | 用途 |
|---|---|
| `futures_quotes` | 国债期货行情 |
| `bond_yields` | 国债收益率曲线 |
| `funding_rates` | 资金利率 |
| `open_market_operations` | 公开市场操作 |
| `policy_news` | 政策/新闻文本 |
| `macro_indicators` | 宏观基本面指标 |
| `ai_text_signals` | 文本结构化信号 |
| `daily_features` | 每日特征 |
| `daily_market_signals` | 每日规则判断 |
| `run_log` | 运行日志 |

### 真实数据质量控制

`validation.py` 是生产流程的质量闸门。校验发生在原始数据入库之后、特征和报告生成之前。

当前要求包括：

- 必须覆盖 `TS`、`TF`、`T`、`TL` 四个国债期货品种。
- 必须覆盖 `1Y`、`2Y`、`5Y`、`10Y`、`30Y` 五个收益率期限。
- 必须覆盖 `DR001`、`DR007`、`R007`、`SHIBOR_ON`、`SHIBOR_7D` 五个资金利率指标。
- 必须覆盖 `LPR_1Y`、`LPR_5Y`、`CPI_YOY`、`PPI_YOY`、`PMI_MFG` 五个宏观指标。
- 公开市场操作和政策新闻允许为空；缺失时对应文本维度按中性处理。
- 六类原始表合计至少有 5 条真实数据。
- `data_source` 中不得出现 sample/mock/fake 一类非真实来源标记。

只要有一项不满足，程序会抛出错误，并在 `run_log` 中记录失败原因。这样做的好处是，报告宁可缺席，也不输出不可靠结论。

### 文本信号层

政策/新闻文本本身是非结构化数据，不能直接参与评分。因此项目把每条新闻转成固定 schema：

| 字段 | 含义 |
|---|---|
| `event_type` | 事件类型，例如货币政策、财政政策、债券供给、资金流动性、通胀等 |
| `summary` | 简短中文摘要 |
| `bond_impact` | 对利率债的方向：`bullish`、`bearish`、`neutral` |
| `affected_maturity` | 影响期限：短端、中段、长端、全曲线或不明确 |
| `related_contracts` | 相关国债期货品种 |
| `confidence` | 1 到 5 的置信度 |
| `reasoning` | 从事件到收益率再到国债期货的传导链条 |
| `model_name` | 文本结构化后端名称 |

项目支持两种文本结构化方式：

| 后端 | 触发条件 | 特点 |
|---|---|---|
| Claude | 设置 `ANTHROPIC_API_KEY` | 可以做更灵活的语义理解，输出后仍会做 schema 校验 |
| 规则引擎 | 默认启用 | 可解释、稳定、无需外部 LLM API |

规则引擎覆盖的事件类型包括：货币政策、资金流动性、债券供给、通胀、宏观增长、财政政策、海外利率、风险偏好、其他。

如果文本无法形成明确利率债方向，会被归入 `other/neutral`。日报中不会把低置信度 `other/neutral` 新闻逐条展开，而是汇总为背景信息，避免报告被无方向文本刷屏。

### 每日特征构造

`features/daily_features.py` 会把原始数据整理成可评分的每日特征。

利率类特征：`yield_10y_change`、`yield_30y_change`、`spread_10y_2y`、`spread_30y_10y`。

资金面特征：`dr007_change`、可用资金利率列表。

公开市场操作特征：`omo_net_injection_amount`、操作记录数量。

期货量价特征：`avg_futures_return`、`avg_volume_change`、覆盖合约数量。

文本特征：`avg_ai_sentiment_score`、文本信号数量。

宏观特征：LPR、CPI 同比、PPI 同比、制造业 PMI 的最新可得值，宏观指标覆盖数量。

这些特征会写入 `daily_features` 表，同时在日报的"特征面板"中展示。

### 市场判断逻辑

`signals/rule_based.py` 使用透明规则生成每日观点。当前输出包括：

- `total_score`：综合评分。
- `market_view`：`bullish`、`bearish` 或 `neutral`。
- `key_drivers`：触发评分的主要理由。
- `risk_notes`：风险和解释边界。
- `details`：评分明细和特征快照。

评分思路如下：

| 维度 | 规则方向 |
|---|---|
| 10Y 收益率明显下行 | 偏多 |
| 10Y 收益率明显上行 | 偏空 |
| 10Y-2Y 利差偏窄 | 小幅偏多 |
| 10Y-2Y 利差偏宽 | 小幅偏空 |
| DR007 下行 | 偏多 |
| DR007 上行 | 偏空 |
| 公开市场明显净投放 | 偏多 |
| 公开市场明显净回笼 | 偏空 |
| 期货上涨且成交活跃度提高 | 偏多 |
| 期货下跌且成交活跃度提高 | 偏空 |
| 文本信号整体偏多 | 偏多 |
| 文本信号整体偏空 | 偏空 |
| 制造业 PMI 低于荣枯线 | 小幅偏多 |
| 制造业 PMI 高于荣枯线 | 小幅偏空 |

最终规则：`total_score >= 2` 为偏多，`total_score <= -2` 为偏空，其他情况为中性。

这套逻辑是研究解释框架，不是交易建议，也不是价格预测模型。

### 日报内容

每日 Markdown 报告位于 `reports_output/YYYY-MM-DD_daily_report.md`。

报告包含：每日市场判断、数据真实性检查、评分拆解、特征面板、数据来源、国债期货概览、收益率曲线概览、资金面概览、宏观基本面概览、公开市场操作概览、政策与新闻结构化解读、核心驱动、风险提示、数据库写入结果、方法说明。

报告中会明确展示当日真实数据条数和来源。例如：

```text
国债期货合约：4 条
国债收益率期限：5 条
资金利率：5 条
公开市场操作：1 条
政策/新闻文本：5 条
宏观基本面指标：5 条
当日真实数据合计：25 条
```

### 环境配置

> **建议先安装 Tushare 数据技能**：本仓库已内置 [tushare.pro 官方 skill](https://github.com/waditu-tushare/skills)（`.claude/skills/tushare-data`），配置 `TUSHARE_TOKEN` 后即可用中文自然语言查询行情、财务、资金流等 Tushare 数据，便于本项目的数据排查与扩展。

建议使用 Python 3.11（与 CI 一致），3.10 及以上可运行。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

复制 `.env.example` 为 `.env`：

```text
DATABASE_PATH=data/bond_futures_monitor.db
REPORTS_OUTPUT_DIR=reports_output
USE_LIVE_DATA=1
TUSHARE_TOKEN=你的 Tushare Token
ANTHROPIC_API_KEY=
```

参数说明：

| 变量 | 是否必需 | 说明 |
|---|---|---|
| `DATABASE_PATH` | 否 | SQLite 数据库路径 |
| `REPORTS_OUTPUT_DIR` | 否 | 日报输出目录 |
| `USE_LIVE_DATA` | 是 | 生产运行要求为 `1` |
| `TUSHARE_TOKEN` | 否 | 可选备用源；AkShare 公开源不可用时尝试 Tushare |
| `ANTHROPIC_API_KEY` | 否 | 启用 Claude 文本结构化；不填则使用规则引擎 |

本地 `.env` 不会提交到仓库。

### 命令行使用

初始化数据库：

```powershell
python -m bond_futures_monitor.cli init-db
```

运行当天流程：

```powershell
python -m bond_futures_monitor.cli run --date today
```

运行指定日期：

```powershell
python -m bond_futures_monitor.cli run --date 2026-06-08
```

只基于已有数据库生成报告：

```powershell
python -m bond_futures_monitor.cli generate-report --date 2026-06-08
```

`run` 与 `generate-report` 均输出两类文件到 `reports_output/`：

- `{date}_daily_report.md` — 当日 Markdown 日报；
- `daily_features.csv` — 累计特征时间序列（每天一行：跨日特征、各维度得分、综合评分与市场观点），每次运行从数据库全量重建，可直接导入 Excel/pandas 做时序分析。

### 自动调度

#### GitHub Actions

仓库已配置每日 workflow：

```yaml
cron: "1 11 * * 1-5"
```

这对应北京时间工作日每天 19:01。

GitHub Actions 无需 Tushare 权限即可运行；如需启用备用源，可在仓库 Secrets 中配置 `TUSHARE_TOKEN`。

workflow 会执行：

1. 拉取仓库（自带版本控制的 SQLite 数据库，含全部历史）。
2. 安装依赖。
3. 解析运行日期。
4. 执行每日监控流程。
5. 运行测试。
6. 提交更新后的日报、特征时间序列 CSV 和数据库。

数据库文件直接纳入 git 版本控制（`data/bond_futures_monitor.db`，在 `.gitattributes` 中标记为二进制）。每次 CI checkout 即获得完整的前期交易日历史，跨日特征（收益率变化、DR007 变化、量能变化）始终可计分，不依赖任何外部缓存。

#### 阿里云 ECS 一键部署

在一台全新的 ECS（Ubuntu / Alibaba Cloud Linux）上：

```bash
export TUSHARE_TOKEN=你的token
export REPO_URL=https://<用户名>:<PAT>@github.com/<用户名>/Bond-Futures-Data-Monitor.git
git clone "$REPO_URL" /opt/bond-futures-monitor
bash /opt/bond-futures-monitor/deploy/aliyun_deploy.sh
```

脚本会自动完成：安装 docker/git（阿里云镜像源）→ 写入 `.env` → 用阿里云 PyPI 镜像构建镜像 → 注册工作日 19:05（北京时间）的 cron。每日运行由 `deploy/run_daily.sh` 承担：拉最新代码与数据库 → 容器内跑流水线 → 提交日报 + CSV + 数据库并推送。

> **注意**：ECS cron 与 GitHub Actions schedule 只能开一个，否则两边同时向 main 推送会产生竞争。切到 ECS 后请注释掉 workflow 中的 `schedule` 块（`workflow_dispatch` 手动触发可保留）。

#### Windows Task Scheduler

本地也可以注册 Windows 定时任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_windows_task.ps1
```

默认时间为本地每天 19:01。任务会调用 `scripts\run_daily_local.ps1`，运行日志写入 `logs/` 目录。

### 测试

运行全部测试：

```powershell
pytest -q --basetemp .pytest_tmp
```

测试覆盖（当前 57 个用例）：采集器在关闭真实数据时必须失败；无 Tushare 权限时使用公开源；行情字段缺失/NaN 必须报错而非填零；中金所与新浪行情的合并回退逻辑；利率、收益率、宏观指标的合理区间校验；宏观月度数据的最新期选取和大小写列名兼容；新闻相关性过滤和 OMO 文本解析；数据库初始化和去重；真实数据质量闸门；文本结构化 schema；规则评分逻辑；日报生成。

### 数据质量与工程权衡

开发过程中踩到的真实数据源问题，以及对应的处理决策（都有注释和测试固化）：

**Tushare `repo_daily` 没有 `rate` 字段。** 回购数据的利率藏在 `weight` 字段（成交量加权平均价），这正是 DR007/R007 官方定盘的定义。已用 SHIBOR_7D 交叉验证（两者长期相差在 1bp 内）确认取数正确。

**宁可失败，不静默填零。** 行情字段缺失或为 NaN 时直接抛错，而不是写入 0.0。一个收盘价为 0 的合约会污染日收益率、量价特征和最终评分，且很难在下游发现；缺一天报告的代价远小于输出一份错误报告。

**所有数值入库前做合理区间校验。** 资金利率限定 (0, 20)%、收益率 (0, 15)%、PMI (20, 80) 等。越界值几乎一定是取错了字段或数据源异常，而不是真实行情，因此按错误处理。

**两个行情源的收益率口径统一。** 中金所日行情的 `daily_return` 基于前结算价；新浪连续合约补缺时也用上一日结算价（缺失则用收盘价）作为基准，保证不同来源的收益率可比。

**宏观数据用"运行日最新可得一期"。** LPR 可能连续数月不变、发布历史可能滞后，固定回看窗口会漏数据，因此 LPR 取全量历史中不晚于运行日的最新一期。同时 `cn_pmi` 接口返回大写列名（`MONTH`/`PMI010000`），与 `cn_cpi`/`cn_ppi` 不一致，列匹配做了大小写兼容。

**重跑幂等。** 任何一天重跑会先清空该日期的全部原始与派生数据再写入，部分失败的运行不会留下脏数据，下次重跑自动自愈。

### 当前边界

这个项目是一个研究数据监控底座，因此仍有一些边界：

- 新闻优先使用 AkShare 财联社电报，Tushare 为备用；公开源当天没有相关内容时文本维度按中性处理。
- 宏观指标的可得性取决于数据源更新进度，记录的是"运行日可知"的最新一期，可能滞后于官方发布。
- 文本过滤是规则式相关性过滤，后续可以加入更强的语义分类模型。
- 市场评分是解释性规则，不是预测模型。
- 当前日报是 Markdown，后续可以扩展成 HTML、仪表盘或可视化图表。
- SQLite 适合轻量研究；如果部署到团队环境，可以替换为 PostgreSQL 或其他数据库。

### 扩展方向

可以继续扩展：增加中债估值、银行间成交、公开市场操作明细等数据；增加历史回测模块，验证规则信号和期货表现之间的关系；增加可视化图表，例如收益率曲线、期限利差、成交量变化和评分趋势；增加更严格的新闻去重和摘要质量控制；增加多模型文本结构化对比；增加 Web dashboard，方便每日查看。

---

## English

### At A Glance

This is a daily real-data monitoring project for Chinese Treasury bond futures research. Every day after 19:00 (Beijing time), it automatically collects six live data streams—futures quotes, government bond yield curves, funding rates, PBOC open-market operations, policy/news text, and macro fundamentals—then cleans, structures, stores, engineers features, extracts text signals, applies rule-based scoring, and generates a daily report.

The core objective is not to predict bond futures prices directly, but to build a stable, auditable, and extensible data research pipeline:

```text
Live data collection -> Cleaning -> Structured storage -> Feature engineering -> Text signals -> Rule-based judgment -> Daily report
```

The production pipeline adheres to one principle: **no sample/mock/fake data**. If a live data source is unavailable, has insufficient coverage, or carries an anomalous source tag, the program fails immediately and logs the reason.

### Navigation

| Looking for | Section |
|---|---|
| Positioning and design philosophy | [Project Positioning](#project-positioning) |
| Architecture and execution flow | [Architecture](#architecture) |
| Six data streams and field details | [Data Sources and Fields](#data-sources-and-fields) |
| Data quality control | [Live Data Quality Control](#live-data-quality-control) |
| Text signals and rule-based scoring | [Text Signal Layer](#text-signal-layer) |
| Environment setup and CLI | [Environment Setup](#environment-setup) |
| Scheduling options | [Scheduling](#scheduling) |
| Engineering trade-offs and boundaries | [Data Quality and Engineering Trade-offs](#data-quality-and-engineering-trade-offs) |

---

### Project Positioning

Daily research on Treasury bond futures typically requires simultaneous attention to several dimensions:

- Futures price, volume, and open interest changes.
- Short-, medium-, and long-end movements of the government bond yield curve.
- Interbank funding conditions and repo rates.
- PBOC open-market operation injection and withdrawal cadence.
- Fiscal policy, monetary policy, bond supply, and risk appetite information.
- Directional signals for rates markets implied in news text.
- Macro fundamentals such as LPR, CPI, PPI, and PMI.

This project consolidates all of these into a single daily automated pipeline, forming a lightweight yet complete research foundation. It is designed as a base for future extensions—additional data sources, stronger text models, visualization dashboards, historical backtesting, or strategy research.

### Design Philosophy

The project follows four design principles.

First, data must be real. Production code retains no sample fallback logic; when live data is missing, the pipeline fails rather than generating a seemingly complete but unreliable report.

Second, the pipeline must be traceable. Every data category carries a `data_source` field; the daily report displays sources; and the database preserves raw data, derived features, and final judgments.

Third, judgments must be explainable. The market view is not a black-box output—it is triggered by yield changes, funding condition shifts, futures volume-price dynamics, and text signals. Every score retains its reasoning.

Fourth, the structure must be extensible. Collectors, feature layer, text layer, scoring layer, and report layer are organized separately, so individual modules can be replaced without rewriting the entire pipeline.

### Architecture

```text
bond_futures_monitor/
  collectors/       # Live data collection: futures, yields, funding rates, OMO, policy news, macro
  ai/               # Policy/news text structuring, outputting fixed-schema rates signals
  features/         # Daily feature engineering: curve, funding, volume-price, text sentiment
  signals/          # Explainable rule-based scoring: bullish, bearish, neutral
  reports/          # Markdown daily report generation
  validation.py     # Live data coverage and source verification
  database.py       # SQLite schema, ingestion, deduplication, refresh, and logging
  cli.py            # Command-line entry point
tests/              # pytest tests
reports_output/     # Generated daily monitoring reports
data/               # SQLite database
scripts/            # Local scheduling scripts
```

During each daily run, `cli.py` executes the following sequence:

1. Parse the run date (defaults to today in Beijing time).
2. Initialize SQLite table schema.
3. Purge stale raw and derived data for the same date, ensuring a re-run is a full refresh.
4. Invoke collectors to fetch live data (including the latest available macro period).
5. Run live-data coverage validation.
6. Generate structured signals from policy/news text.
7. Engineer daily features.
8. Produce rule-based market judgment.
9. Write to database and generate the Markdown daily report.

### Data Sources and Fields

#### Bond Futures Quotes

Futures quotes are used to observe price direction, trading activity, and open interest changes.

| Field | Description |
|---|---|
| `date` | Run date |
| `contract` | Bond futures product: `TS`, `TF`, `T`, `TL` |
| `close_price` | Closing price |
| `daily_return` | Daily return |
| `volume` | Trading volume |
| `open_interest` | Open interest |
| `data_source` | Data source and query date |

Data is sourced primarily from AKShare's CFFEX daily quotes interface. The project requires coverage of four bond futures products:

- `TS`: 2-year Treasury bond futures
- `TF`: 5-year Treasury bond futures
- `T`: 10-year Treasury bond futures
- `TL`: 30-year Treasury bond futures

If the CFFEX interface does not return all four products, the program falls back to AKShare's Sina dominant continuous contract quotes. If neither source satisfies coverage requirements, the pipeline fails.

#### Government Bond Yield Curve

The yield curve is the core data for assessing the rates-market environment. The project tries Tushare `yc_cb` first and falls back to public CCDC curve data exposed by AkShare when permission is unavailable.

| Tenor | Research Meaning |
|---|---|
| `1Y` | Short-end rate, sensitive to funding conditions and monetary policy expectations |
| `2Y` | Short-to-medium transition, related to `TS` and `TF` |
| `5Y` | Medium-segment curve, more sensitive to `TF` |
| `10Y` | Long-end core benchmark, more sensitive to `T` |
| `30Y` | Ultra-long end, more sensitive to `TL` and bond supply expectations |

The project computes:

- `yield_10y_change`: 10Y yield change relative to the previous available date.
- `yield_30y_change`: 30Y yield change relative to the previous available date.
- `spread_10y_2y`: 10Y-2Y spread, for observing curve steepening or flattening.
- `spread_30y_10y`: 30Y-10Y spread, for observing ultra-long-end term premium.

#### Funding Rates

Funding conditions affect bond carrying costs and short-end rate expectations. By default, the project uses AkShare to read CFETS repo fixings and public Shibor data; Tushare is only a fallback.

| Indicator | Description |
|---|---|
| `DR001` | Interbank depository institutions overnight pledged repo rate |
| `DR007` | Interbank depository institutions 7-day pledged repo rate |
| `R007` | Interbank 7-day pledged repo rate |
| `SHIBOR_ON` | Overnight Shibor |
| `SHIBOR_7D` | 7-day Shibor |

`DR007` serves as the core funding-condition indicator:

- `DR007` declining: marginal easing, generally favorable for rates markets.
- `DR007` rising: marginal tightening, generally pressuring rates markets.

#### Open-Market Operations

Open-market operations directly reflect PBOC liquidity injection and withdrawal in the banking system, linking monetary policy, funding conditions, and bond futures pricing. The project parses PBOC reverse-repo information from live news text.

| Field | Description |
|---|---|
| `operation_type` | Operation type, e.g. reverse repo, outright reverse repo |
| `tenor_days` | Operation tenor, normalized to days |
| `operation_amount` | Daily injection amount, in CNY 100 million |
| `maturity_amount` | Daily maturing amount, in CNY 100 million |
| `net_injection_amount` | Net injection; positive for injection, negative for withdrawal |
| `source_title` | Original news headline from which the record was parsed |
| `data_source` | Data source |

The parsing logic prioritizes keywords such as PBOC, open market, reverse repo, maturity, net injection, and net withdrawal, using regex to extract amounts and tenors. Since the operation rate field is frequently missing in public news, the daily report does not display it.

#### Policy and News Text

Policy/news text comes primarily from AkShare's public CLS telegraph feed, with Tushare `news(src="cls")` as a fallback. Whole-market noise is filtered out; when no relevant item is available, the text dimension is scored neutral without blocking the report.

The filtering logic has three layers:

1. Retain high-relevance anchors, e.g. PBOC, government bonds, bond futures, rates bonds, local government bonds, special bonds, Ministry of Finance, NDRC, interbank, DR007, Shibor, MLF, LPR, RRR cut, rate cut, monetary policy.
2. Identify broad financial noise, e.g. ETF, equities, share buyback, employee stock ownership, individual stock holdings increase, position building, major asset restructuring, corporate debt financing instruments.
3. For text containing noise terms, require stronger government-bond or policy anchors to avoid misclassifying individual stock news, overseas equity market news, or corporate financing news as bond-futures-relevant.

The goal is not to filter as aggressively as possible, but to reduce "seemingly financial but weakly bond-futures-related" text from entering the structured report.

#### Macro Fundamentals

Macro data determines the medium-term trend backdrop for rates markets. The project fetches five core indicators from public AkShare sources, with Tushare as a fallback, recording the **latest published value available as of the run date** and preserving the data vintage in `period`:

| Indicator | Source API | Research Meaning |
|---|---|---|
| `LPR_1Y` | `macro_china_lpr` | 1-year Loan Prime Rate, policy rate anchor |
| `LPR_5Y` | `macro_china_lpr` | 5-year+ LPR, more related to real estate and long end |
| `CPI_YOY` | `macro_china_cpi` | CPI year-over-year, inflation pressure |
| `PPI_YOY` | `macro_china_ppi` | PPI year-over-year, industrial prices and nominal growth |
| `PMI_MFG` | `macro_china_pmi` | Manufacturing PMI, activity vs. expansion/contraction threshold |

Macro indicators are released monthly or irregularly, naturally asynchronous with daily data. The project records the latest value available as of the run date, ensuring each daily report has complete macro context while preserving point-in-time ("known at the time") information and avoiding look-ahead bias.

### Data Cleaning and Structuring

Collected data undergoes basic cleaning before database ingestion:

- Dates normalized to `YYYY-MM-DD`.
- Quote values normalized to floating point.
- Bond futures products normalized to `TS`, `TF`, `T`, `TL`.
- Yield tenors normalized to `1Y`, `2Y`, `5Y`, `10Y`, `30Y`.
- Funding rate names normalized to `DR001`, `DR007`, `R007`, `SHIBOR_ON`, `SHIBOR_7D`.
- OMO amounts normalized to CNY 100 million.
- Every record retains `data_source` for traceability.
- Re-running the same date purges old data before writing new data, preventing stale and fresh results from mixing.

The database uses SQLite, suitable for local research, automated tasks, and lightweight deployment. Core tables include:

| Table | Purpose |
|---|---|
| `futures_quotes` | Bond futures quotes |
| `bond_yields` | Government bond yield curve |
| `funding_rates` | Funding rates |
| `open_market_operations` | Open-market operations |
| `policy_news` | Policy/news text |
| `macro_indicators` | Macro fundamentals |
| `ai_text_signals` | Text structuring signals |
| `daily_features` | Daily features |
| `daily_market_signals` | Daily rule-based judgments |
| `run_log` | Run log |

### Live Data Quality Control

`validation.py` is the quality gate in the production pipeline. Validation occurs after raw data ingestion but before feature engineering and report generation.

Current requirements:

- Must cover `TS`, `TF`, `T`, `TL`—all four bond futures products.
- Must cover `1Y`, `2Y`, `5Y`, `10Y`, `30Y`—all five yield tenors.
- Must cover `DR001`, `DR007`, `R007`, `SHIBOR_ON`, `SHIBOR_7D`—all five funding rate indicators.
- Must cover `LPR_1Y`, `LPR_5Y`, `CPI_YOY`, `PPI_YOY`, `PMI_MFG`—all five macro indicators.
- OMO and policy/news rows may be empty; their text-derived dimensions are scored neutral when unavailable.
- Six raw tables combined must have at least 5 real data records.
- `data_source` must not contain sample/mock/fake or similar non-live source tags.

If any requirement is unmet, the program raises an error and records the failure reason in `run_log`. The benefit: a report is better absent than unreliable.

### Text Signal Layer

Policy/news text is inherently unstructured and cannot directly participate in scoring. The project therefore converts each news item into a fixed schema:

| Field | Description |
|---|---|
| `event_type` | Event type, e.g. monetary policy, fiscal policy, bond supply, funding liquidity, inflation |
| `summary` | Brief Chinese summary |
| `bond_impact` | Direction for rates markets: `bullish`, `bearish`, `neutral` |
| `affected_maturity` | Affected tenor: short end, medium, long end, whole curve, or unclear |
| `related_contracts` | Related bond futures products |
| `confidence` | Confidence from 1 to 5 |
| `reasoning` | Transmission chain from event to yields to bond futures |
| `model_name` | Text structuring backend name |

The project supports two text structuring backends:

| Backend | Trigger | Characteristics |
|---|---|---|
| Claude | Set `ANTHROPIC_API_KEY` | More flexible semantic understanding; output still undergoes schema validation |
| Rule engine | Enabled by default | Explainable, stable, no external LLM API required |

The rule engine covers event types including: monetary policy, funding liquidity, bond supply, inflation, macro growth, fiscal policy, overseas rates, risk appetite, and other.

If text cannot form a clear rates-market direction, it is classified as `other/neutral`. The daily report does not expand low-confidence `other/neutral` news item by item; instead it aggregates them as background information to avoid flooding the report with directionless text.

### Daily Feature Engineering

`features/daily_features.py` consolidates raw data into scorable daily features.

Rate features: `yield_10y_change`, `yield_30y_change`, `spread_10y_2y`, `spread_30y_10y`.

Funding features: `dr007_change`, available funding rate list.

OMO features: `omo_net_injection_amount`, number of operation records.

Futures volume-price features: `avg_futures_return`, `avg_volume_change`, number of covered contracts.

Text features: `avg_ai_sentiment_score`, number of text signals.

Macro features: latest available values of LPR, CPI YoY, PPI YoY, manufacturing PMI; macro indicator coverage count.

These features are written to the `daily_features` table and displayed in the report's "Feature Panel."

### Market Judgment Logic

`signals/rule_based.py` uses transparent rules to generate the daily view. Current outputs include:

- `total_score`: composite score.
- `market_view`: `bullish`, `bearish`, or `neutral`.
- `key_drivers`: primary reasons triggering the score.
- `risk_notes`: risk and interpretation boundaries.
- `details`: score breakdown and feature snapshot.

Scoring logic:

| Dimension | Rule Direction |
|---|---|
| 10Y yield declines significantly | Bullish |
| 10Y yield rises significantly | Bearish |
| 10Y-2Y spread narrows | Mildly bullish |
| 10Y-2Y spread widens | Mildly bearish |
| DR007 declines | Bullish |
| DR007 rises | Bearish |
| OMO significant net injection | Bullish |
| OMO significant net withdrawal | Bearish |
| Futures rise with increasing activity | Bullish |
| Futures fall with increasing activity | Bearish |
| Text signals overall bullish | Bullish |
| Text signals overall bearish | Bearish |
| Manufacturing PMI below threshold | Mildly bullish |
| Manufacturing PMI above threshold | Mildly bearish |

Final rule: `total_score >= 2` is bullish, `total_score <= -2` is bearish, otherwise neutral.

This logic is a research interpretation framework, not trading advice, and not a price prediction model.

### Daily Report Contents

The daily Markdown report is located at `reports_output/YYYY-MM-DD_daily_report.md`.

The report includes: daily market judgment, data authenticity check, score breakdown, feature panel, data sources, bond futures overview, yield curve overview, funding conditions overview, macro fundamentals overview, open-market operations overview, structured policy/news interpretation, key drivers, risk notes, database write results, and methodology notes.

The report explicitly displays the day's real data record counts and sources. For example:

```text
Bond futures contracts: 4 records
Government bond yield tenors: 5 records
Funding rates: 5 records
Open-market operations: 1 record
Policy/news text: 5 records
Macro fundamentals: 5 records
Total live data for the day: 25 records
```

### Environment Setup

> **Tip: Install the Tushare data skill first**: This repository includes the [tushare.pro official skill](https://github.com/waditu-tushare/skills) (`.claude/skills/tushare-data`). After configuring `TUSHARE_TOKEN`, you can query quotes, financials, fund flows, and other Tushare data in natural Chinese, facilitating data troubleshooting and extension for this project.

Python 3.11 is recommended (consistent with CI); 3.10+ is supported.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Copy `.env.example` to `.env`:

```text
DATABASE_PATH=data/bond_futures_monitor.db
REPORTS_OUTPUT_DIR=reports_output
USE_LIVE_DATA=1
TUSHARE_TOKEN=your Tushare token
ANTHROPIC_API_KEY=
```

Parameter reference:

| Variable | Required | Description |
|---|---|---|
| `DATABASE_PATH` | No | SQLite database path |
| `REPORTS_OUTPUT_DIR` | No | Daily report output directory |
| `USE_LIVE_DATA` | Yes | Must be `1` for production runs |
| `TUSHARE_TOKEN` | No | Optional fallback when an AkShare public source is unavailable |
| `ANTHROPIC_API_KEY` | No | Enables Claude text structuring; omit to use the rule engine |

The local `.env` is not committed to the repository.

### CLI Usage

Initialize the database:

```powershell
python -m bond_futures_monitor.cli init-db
```

Run today's pipeline:

```powershell
python -m bond_futures_monitor.cli run --date today
```

Run a specific date:

```powershell
python -m bond_futures_monitor.cli run --date 2026-06-08
```

Generate a report from existing database only:

```powershell
python -m bond_futures_monitor.cli generate-report --date 2026-06-08
```

Both `run` and `generate-report` output two file types to `reports_output/`:

- `{date}_daily_report.md` — the day's Markdown report;
- `daily_features.csv` — cumulative feature time series (one row per day: cross-day features, dimension scores, composite score, and market view), fully rebuilt from the database on each run, directly importable into Excel/pandas for time-series analysis.

### Scheduling

#### GitHub Actions

The repository has a daily workflow configured:

```yaml
cron: "1 11 * * 1-5"
```

This corresponds to 19:01 Beijing time on weekdays.

GitHub Actions can run without Tushare permissions. Configure `TUSHARE_TOKEN` in repository Secrets only to enable the optional fallback.

The workflow executes:

1. Checkout the repository (includes the version-controlled SQLite database with full history).
2. Install dependencies.
3. Parse the run date.
4. Execute the daily monitoring pipeline.
5. Run tests.
6. Commit updated reports, feature time-series CSV, and database.

The database file is directly under git version control (`data/bond_futures_monitor.db`, marked as binary in `.gitattributes`). Each CI checkout obtains complete prior trading-day history; cross-day features (yield changes, DR007 changes, volume changes) are always computable without any external cache.

#### Alibaba Cloud ECS One-Click Deployment

On a fresh ECS instance (Ubuntu / Alibaba Cloud Linux):

```bash
export TUSHARE_TOKEN=your_token
export REPO_URL=https://<username>:<PAT>@github.com/<username>/Bond-Futures-Data-Monitor.git
git clone "$REPO_URL" /opt/bond-futures-monitor
bash /opt/bond-futures-monitor/deploy/aliyun_deploy.sh
```

The script automatically: installs docker/git (Alibaba Cloud mirror) → writes `.env` → builds the image using Alibaba Cloud PyPI mirror → registers a weekday 19:05 (Beijing time) cron. Daily execution is handled by `deploy/run_daily.sh`: pull latest code and database → run pipeline in container → commit report + CSV + database and push.

> **Note**: ECS cron and GitHub Actions schedule should not both be active—simultaneous pushes to main from both will conflict. After switching to ECS, comment out the `schedule` block in the workflow (`workflow_dispatch` manual trigger can remain).

#### Windows Task Scheduler

A local Windows scheduled task can also be registered:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_windows_task.ps1
```

Default time is 19:01 local daily. The task invokes `scripts\run_daily_local.ps1`; run logs are written to the `logs/` directory.

### Historical rebuild

```powershell
python -m bond_futures_monitor.backfill --year 2026
```

Rebuilds every CFFEX trading session from January 1 through the latest completed
19:01 Beijing publication window (never future dates). Reuses stored real market
and news snapshots, fetches missing quotes/yields/funding, and recomputes macro,
features, scores and the current report layout in chronological order. Monthly
macro values are selected by **official NBS publication date**, not merely data
month. The prior 120 CFFEX trading sessions are loaded first: 60 sessions seed the
longest rolling window, then 60 sessions produce fully initialized historical
scores. Warmup sessions are not counted as yearly reports. Missing warmup inputs
block report regeneration instead of silently publishing underfilled windows.
Funding scoring consistently prefers the public FDR007 fixing history; weighted
DR/R quotes remain separately displayed when available, never spliced into FDR/FR.

Report generation rejects unexplained empty cells, placeholder dashes, `缺失`,
and non-finite values before writing the Markdown file. Volume and open-interest
five-session changes use the observation five trading sessions earlier, not five
calendar days. Genuine unavailable comparisons explain their missing input;
unpublished/uncollected macro observations are never filled using future releases.
Use `python -m scripts.verify_warmup --render-reports` to rerender the stored 2026
reports and check every table, warmed-up market panel, and activity comparison.

Shared histories and per-day responses are cached under `data/backfill_*` for
resumption. A SQLite backup is made there before the first rebuild. Failed days
keep their old database snapshot and are listed in
`reports_output/backfill_2026_manifest.json`; rerun the same command to retry.
Historical OMO is supplemented from official PBC notices only when maturity
records are available. Historical news and optional research fields without stored
records remain explicitly unavailable, not zero. ChinaBond fallback 2Y yields
are explicitly labeled as linear interpolation of 1Y/3Y. The yearly report index
is `reports_output/2026_index.md`. This command does not commit or push files.

### Testing

Run all tests:

```powershell
pytest -q --basetemp .pytest_tmp
```

Test coverage (currently 57 cases): collectors must fail when live data is disabled; public sources must work without Tushare permissions; missing/NaN quote fields must raise errors rather than filling zeros; CFFEX and Sina quote merge fallback logic; reasonable-range validation for rates, yields, and macro indicators; latest-period selection and case-insensitive column matching for monthly macro data; news relevance filtering and OMO text parsing; database initialization and deduplication; live-data quality gate; text structuring schema; rule-based scoring logic; daily report generation.

### Data Quality and Engineering Trade-offs

Real data-source issues encountered during development, and the corresponding design decisions (all codified with comments and tests):

**Tushare `repo_daily` has no `rate` field.** The repo rate is hidden in the `weight` field (volume-weighted average price), which is precisely the official fixing definition for DR007/R007. Cross-validated against SHIBOR_7D (long-term difference within 1bp) to confirm correct extraction.

**Fail rather than silently fill zeros.** When quote fields are missing or NaN, the program raises an error instead of writing 0.0. A contract with a zero closing price would contaminate daily returns, volume-price features, and final scores, and would be difficult to detect downstream; the cost of missing one day's report is far less than outputting an incorrect one.

**All values undergo reasonable-range validation before ingestion.** Funding rates bounded to (0, 20)%, yields to (0, 15)%, PMI to (20, 80), etc. Out-of-range values are almost certainly field-extraction errors or data-source anomalies rather than real quotes, and are therefore treated as errors.

**Yield calibration unified across two quote sources.** CFFEX daily quotes compute `daily_return` from the previous settlement price; when Sina continuous contracts fill gaps, the previous day's settlement price (or closing price if settlement is missing) is used as the base, ensuring comparability across sources.

**Macro data uses "latest available period as of run date."** LPR may remain unchanged for months and publication history may lag; a fixed lookback window would miss data, so LPR takes the latest period no later than the run date from full history. Additionally, the `cn_pmi` API returns uppercase column names (`MONTH`/`PMI010000`), inconsistent with `cn_cpi`/`cn_ppi`; column matching is case-insensitive.

**Idempotent re-runs.** Re-running any date first purges all raw and derived data for that date before writing; partially failed runs leave no dirty data, and the next re-run self-heals automatically.

### Current Boundaries

This project is a research data monitoring foundation, so certain boundaries remain:

- News sourcing prefers AkShare's public CLS feed with Tushare as fallback; the text dimension is neutral when no relevant item is available.
- Macro indicator availability depends on data-source update progress; the recorded value is the "latest known as of run date" and may lag official publication.
- Text filtering is rule-based relevance filtering; stronger semantic classification models can be added later.
- Market scoring is an explanatory rule framework, not a predictive model.
- The current report is Markdown; it can be extended to HTML, dashboards, or visualizations.
- SQLite suits lightweight research; for team deployment, it can be replaced with PostgreSQL or another database.

### Extension Directions

Possible extensions include: adding ChinaBond valuations, interbank transactions, and OMO detail data; adding a historical backtesting module to validate the relationship between rule signals and futures performance; adding visualizations such as yield curve charts, term spreads, volume changes, and score trends; adding stricter news deduplication and summary quality control; adding multi-model text structuring comparison; and adding a web dashboard for daily viewing.

---

## License

MIT License.
