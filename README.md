# 中国国债期货真实数据监控 | Bond Futures Real-Data Monitor

这是一个面向中国国债期货研究的每日真实数据监控项目。项目每天北京时间 19:00 后自动抓取六路真实数据——期货行情、国债收益率曲线、资金利率、央行公开市场操作、政策新闻文本、宏观基本面指标——完成清洗、结构化、入库、特征构造、文本信号提取、规则评分和日报生成。

项目的核心目标不是直接预测国债期货价格，而是搭建一条稳定、可复核、可扩展的数据研究链路：

```text
真实数据采集 -> 数据清洗 -> 结构化入库 -> 特征构造 -> 文本信号 -> 规则判断 -> 每日报告
```

生产流程坚持一个原则：**不使用 sample/mock/fake 数据**。如果真实数据源不可用、覆盖不足或来源标记异常，程序会直接失败，并在运行日志中记录原因。

## 项目定位

国债期货的日常研究通常需要同时关注几个层面：

- 期货自身的价格、成交量和持仓变化。
- 国债收益率曲线的短端、中端、长端变化。
- 银行间资金面和回购利率。
- 央行公开市场操作的投放与回笼节奏。
- 财政、货币政策、债券供给和风险偏好相关信息。
- 新闻文本中隐含的利率债方向性信号。
- LPR、CPI、PPI、PMI 等宏观基本面数据。

这个项目把这些信息放进同一条每日自动化流程中，形成一个轻量但完整的研究底座。它适合作为后续扩展的基础，例如加入更多数据源、更多文本模型、可视化面板、历史回测或策略研究。

## 设计思路

项目设计时遵循四个思路。

第一，数据必须真实。生产代码不再保留样例回退逻辑，真实数据缺失时宁可失败，也不生成看似完整但不可用的报告。

第二，链路必须可追踪。每一类数据都会写入 `data_source` 字段，日报会展示来源，数据库中也保留原始数据、派生特征和最终判断。

第三，判断必须可解释。市场观点不是黑箱输出，而是由收益率变化、资金面变化、期货量价关系和文本信号共同触发。每一项评分都会保留理由。

第四，结构必须便于扩展。采集器、特征层、文本层、评分层、报告层分开组织，未来可以替换单个模块，而不需要重写整条链路。

## 总体架构

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

## 数据源与字段

### 国债期货行情

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

### 国债收益率曲线

收益率曲线是判断利率债环境的核心数据。项目从 Tushare `yc_cb` 获取中国国债收益率曲线。

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

### 资金利率

资金面影响债券持仓成本和短端利率预期。项目从 Tushare 获取回购利率和 Shibor。

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

### 公开市场操作

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

### 政策与新闻文本

政策和新闻文本来自 Tushare `news(src="cls")`。由于该接口返回的是全市场新闻，项目额外做了相关性过滤，尽量保留真正与中国利率债、国债期货、财政货币政策、债券供给和银行间资金面相关的内容。

过滤逻辑分为三层：

1. 保留高相关锚点，例如央行、人民银行、国债、国债期货、利率债、地方债、专项债、特别国债、财政部、国家发改委、银行间、DR007、Shibor、MLF、LPR、降准、降息、货币政策。
2. 识别泛金融噪声，例如 ETF、股票、股份回购、员工持股、个股增持、资金加仓、重大资产重组、公司债务融资工具等。
3. 对含噪声词的文本要求更高的政府债或政策锚点，避免把个股新闻、海外股市新闻或公司融资新闻误判为国债期货相关信息。

这一步的目标不是过滤得越多越好，而是减少“看似金融、实际和国债期货关系很弱”的文本进入结构化报告。

### 宏观基本面指标

宏观数据决定利率债的中期趋势背景。项目从 Tushare 获取五个核心指标，记录的是**运行日可得的最新一期发布值**，并在 `period` 字段保留数据期：

| 指标 | 来源接口 | 研究含义 |
|---|---|---|
| `LPR_1Y` | `shibor_lpr` | 1 年期贷款市场报价利率，政策利率锚 |
| `LPR_5Y` | `shibor_lpr` | 5 年期以上 LPR，与地产和长端更相关 |
| `CPI_YOY` | `cn_cpi` | CPI 同比，通胀压力 |
| `PPI_YOY` | `cn_ppi` | PPI 同比，工业品价格和名义增长 |
| `PMI_MFG` | `cn_pmi` | 制造业 PMI，景气度与荣枯线对比 |

宏观指标按月度或不定期发布，与日频数据天然不同步。项目的处理方式是按运行日落库当时最新值，既保证每日报告有完整宏观背景，也保留了"当时可知"的时点信息，避免未来数据泄漏。

## 数据清洗与结构化

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

## 真实数据质量控制

`validation.py` 是生产流程的质量闸门。校验发生在原始数据入库之后、特征和报告生成之前。

当前要求包括：

- 必须覆盖 `TS`、`TF`、`T`、`TL` 四个国债期货品种。
- 必须覆盖 `1Y`、`2Y`、`5Y`、`10Y`、`30Y` 五个收益率期限。
- 必须覆盖 `DR001`、`DR007`、`R007`、`SHIBOR_ON`、`SHIBOR_7D` 五个资金利率指标。
- 必须覆盖 `LPR_1Y`、`LPR_5Y`、`CPI_YOY`、`PPI_YOY`、`PMI_MFG` 五个宏观指标。
- 必须至少解析到 1 条公开市场操作记录。
- 当天至少有 1 条固定收益相关政策/新闻文本。
- 六类原始表合计至少有 5 条真实数据。
- `data_source` 中不得出现 sample/mock/fake 一类非真实来源标记。

只要有一项不满足，程序会抛出错误，并在 `run_log` 中记录失败原因。这样做的好处是，报告宁可缺席，也不输出不可靠结论。

## 文本信号层

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

规则引擎覆盖的事件类型包括：

- 货币政策
- 资金流动性
- 债券供给
- 通胀
- 宏观增长
- 财政政策
- 海外利率
- 风险偏好
- 其他

如果文本无法形成明确利率债方向，会被归入 `other/neutral`。日报中不会把低置信度 `other/neutral` 新闻逐条展开，而是汇总为背景信息，避免报告被无方向文本刷屏。

## 每日特征构造

`features/daily_features.py` 会把原始数据整理成可评分的每日特征。

利率类特征：

- `yield_10y_change`
- `yield_30y_change`
- `spread_10y_2y`
- `spread_30y_10y`

资金面特征：

- `dr007_change`
- 可用资金利率列表

公开市场操作特征：

- `omo_net_injection_amount`
- 操作记录数量

期货量价特征：

- `avg_futures_return`
- `avg_volume_change`
- 覆盖合约数量

文本特征：

- `avg_ai_sentiment_score`
- 文本信号数量

宏观特征：

- LPR、CPI 同比、PPI 同比、制造业 PMI 的最新可得值
- 宏观指标覆盖数量

这些特征会写入 `daily_features` 表，同时在日报的“特征面板”中展示。

## 市场判断逻辑

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

最终规则：

- `total_score >= 2`：偏多。
- `total_score <= -2`：偏空。
- 其他情况：中性。

这套逻辑是研究解释框架，不是交易建议，也不是价格预测模型。

## 日报内容

每日 Markdown 报告位于：

```text
reports_output/YYYY-MM-DD_daily_report.md
```

报告包含：

- 每日市场判断。
- 数据真实性检查。
- 评分拆解。
- 特征面板。
- 数据来源。
- 国债期货概览。
- 收益率曲线概览。
- 资金面概览。
- 宏观基本面概览。
- 公开市场操作概览。
- 政策与新闻结构化解读。
- 核心驱动。
- 风险提示。
- 数据库写入结果。
- 方法说明。

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

## 环境配置

建议使用 Python 3.11（与 CI 一致），3.10 及以上可运行。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
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
| `TUSHARE_TOKEN` | 是 | 收益率、资金利率和新闻数据需要 |
| `ANTHROPIC_API_KEY` | 否 | 启用 Claude 文本结构化；不填则使用规则引擎 |

本地 `.env` 不会提交到仓库。

## 命令行使用

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

## 自动调度

### GitHub Actions

仓库已配置每日 workflow：

```yaml
cron: "1 11 * * 1-5"
```

这对应北京时间工作日每天 19:01。

GitHub Actions 运行前需要在仓库 Secrets 中配置：

```text
TUSHARE_TOKEN
```

workflow 会执行：

1. 拉取仓库（自带版本控制的 SQLite 数据库，含全部历史）。
2. 安装依赖。
3. 解析运行日期。
4. 执行每日监控流程。
5. 运行测试。
6. 提交更新后的日报、特征时间序列 CSV 和数据库。

数据库文件直接纳入 git 版本控制（`data/bond_futures_monitor.db`，在 `.gitattributes` 中标记为二进制）。每次 CI checkout 即获得完整的前期交易日历史，跨日特征（收益率变化、DR007 变化、量能变化）始终可计分，不依赖任何外部缓存。

### 阿里云 ECS 一键部署

在一台全新的 ECS（Ubuntu / Alibaba Cloud Linux）上：

```bash
export TUSHARE_TOKEN=你的token
export REPO_URL=https://<用户名>:<PAT>@github.com/<用户名>/Bond-Futures-Data-Monitor.git
git clone "$REPO_URL" /opt/bond-futures-monitor
bash /opt/bond-futures-monitor/deploy/aliyun_deploy.sh
```

脚本会自动完成：安装 docker/git（阿里云镜像源）→ 写入 `.env` → 用阿里云 PyPI 镜像构建镜像 → 注册工作日 19:05（北京时间）的 cron。每日运行由 `deploy/run_daily.sh` 承担：拉最新代码与数据库 → 容器内跑流水线 → 提交日报 + CSV + 数据库并推送。

> **注意**：ECS cron 与 GitHub Actions schedule 只能开一个，否则两边同时向 main 推送会产生竞争。切到 ECS 后请注释掉 workflow 中的 `schedule` 块（`workflow_dispatch` 手动触发可保留）。

### Windows Task Scheduler

本地也可以注册 Windows 定时任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_windows_task.ps1
```

默认时间为本地每天 19:01。任务会调用：

```powershell
scripts\run_daily_local.ps1
```

运行日志会写入 `logs/` 目录。

## 测试

运行全部测试：

```powershell
pytest -q --basetemp .pytest_tmp
```

测试覆盖（当前 48 个用例）：

- 采集器在关闭真实数据时必须失败。
- Tushare 采集器缺少 token 时必须失败。
- 行情字段缺失/NaN 必须报错而非填零。
- 中金所与新浪行情的合并回退逻辑。
- 利率、收益率、宏观指标的合理区间校验。
- 宏观月度数据的最新期选取和大小写列名兼容。
- 新闻相关性过滤和 OMO 文本解析。
- 数据库初始化和去重。
- 真实数据质量闸门。
- 文本结构化 schema。
- 规则评分逻辑。
- 日报生成。

## 数据质量与工程权衡

开发过程中踩到的真实数据源问题，以及对应的处理决策（都有注释和测试固化）：

**Tushare `repo_daily` 没有 `rate` 字段。** 回购数据的利率藏在 `weight` 字段（成交量加权平均价），这正是 DR007/R007 官方定盘的定义。已用 SHIBOR_7D 交叉验证（两者长期相差在 1bp 内）确认取数正确。

**宁可失败，不静默填零。** 行情字段缺失或为 NaN 时直接抛错，而不是写入 0.0。一个收盘价为 0 的合约会污染日收益率、量价特征和最终评分，且很难在下游发现；缺一天报告的代价远小于输出一份错误报告。

**所有数值入库前做合理区间校验。** 资金利率限定 (0, 20)%、收益率 (0, 15)%、PMI (20, 80) 等。越界值几乎一定是取错了字段或数据源异常，而不是真实行情，因此按错误处理。

**两个行情源的收益率口径统一。** 中金所日行情的 `daily_return` 基于前结算价；新浪连续合约补缺时也用上一日结算价（缺失则用收盘价）作为基准，保证不同来源的收益率可比。

**宏观数据用"运行日最新可得一期"。** LPR 可能连续数月不变、发布历史可能滞后，固定回看窗口会漏数据，因此 LPR 取全量历史中不晚于运行日的最新一期。同时 `cn_pmi` 接口返回大写列名（`MONTH`/`PMI010000`），与 `cn_cpi`/`cn_ppi` 不一致，列匹配做了大小写兼容。

**重跑幂等。** 任何一天重跑会先清空该日期的全部原始与派生数据再写入，部分失败的运行不会留下脏数据，下次重跑自动自愈。

## 当前边界

这个项目是一个研究数据监控底座，因此仍有一些边界：

- 新闻来源目前主要使用 Tushare 财联社接口，覆盖范围取决于接口当天返回内容。
- 宏观指标的可得性取决于数据源更新进度，记录的是"运行日可知"的最新一期，可能滞后于官方发布。
- 文本过滤是规则式相关性过滤，后续可以加入更强的语义分类模型。
- 市场评分是解释性规则，不是预测模型。
- 当前日报是 Markdown，后续可以扩展成 HTML、仪表盘或可视化图表。
- SQLite 适合轻量研究；如果部署到团队环境，可以替换为 PostgreSQL 或其他数据库。

## 扩展方向

可以继续扩展：

- 增加中债估值、银行间成交、公开市场操作明细等数据。
- 增加历史回测模块，验证规则信号和期货表现之间的关系。
- 增加可视化图表，例如收益率曲线、期限利差、成交量变化和评分趋势。
- 增加更严格的新闻去重和摘要质量控制。
- 增加多模型文本结构化对比。
- 增加 Web dashboard，方便每日查看。

## English Summary

Bond Futures Real-Data Monitor is a daily monitoring pipeline for Chinese Treasury bond futures research. It collects real market data, yield-curve data, funding rates, PBOC open-market operations, policy/news text, and macro fundamentals (LPR/CPI/PPI/PMI) from AKShare and Tushare, then cleans, stores, structures, scores, and reports the results.

The production pipeline does not use sample, mock, or fake fallback data. If live-data coverage is incomplete, the run fails fast and records the reason.
