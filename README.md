# MODI · AI 交易团队

手机优先的中文静态交易看板。黑底、荧光绿像素描边、六个 SVG 静态机器人。行情直接读取 OKX 公共接口，交易数据只读取经过白名单清洗的同源 JSON。没有密钥、登录、账户号码或私有交易接口。

## 运行

```bash
cd /workspace/crypto-panel
python3 tools/make_snapshot.py
python3 tools/validate_account.py paper/account.json
python3 -m http.server 8008 --bind 127.0.0.1
```

打开 <http://127.0.0.1:8008/>。`config.js` 配置关注币 `symbol` 和 `startDate`，默认 `2026-11-02`。DAY 1 从该日期 UTC+7 零点开始，之后按 UTC+7 日界递增，实时时钟也使用 UTC+7。

首页顺序：

1. 六张团队卡 + FILLS / SIZE，两行四列；手机固定两列。团队报告在卡内展开。
2. 像素交易室：关注币 1H/4H K 线和 EMA20/50/200，六个静态工位及状态灯；主屏下方显示总盈亏与持仓数。
3. BALANCE 合计余额、模式标签和合计权益面积图。
4. 当前持仓、最近成交、每个策略的日亏进度与只读开关状态。
5. 单币分析与 thresholds：量 / RSI / MACD、六条件、支撑阻力、会议结论、风险规则和实际策略参数。
6. 可折叠的团队时间线、BT60、行情前 30、旧四盘历史。

保留 `#/market`（搜索排序）、`#/coin/ZEC-USDT-SWAP`（独立单币分析）、`#/paper`（原账户明细与历史曲线）路由。手机宽表仅在自身容器内左右滑动，当前持仓的币种列固定。所有缺失数字显示“—”，缺失记录显示“暂无”；缺失策略目录显示“未启动”，不填入示例资金或价格。

## 统一账户快照：模拟盘 / 实盘共用

**首页唯一交易数据来源是 `paper/account.json`**，不从旧账户表拼当前总额。生成器目前固定 `mode=paper`，只读 `/workspace/crypto-bot/paper_main`、`paper_meeting`。目录不存在时发布未启动占位；目录存在但文件损坏或缺少必要数据时拒绝替换旧快照。不会写入 `/workspace/crypto-bot` 或执行交易程序。

契约入口（完整字段约束见 `tools/account.schema.json`）：

```text
{
  mode: "paper" | "live",
  source: 公开来源说明,
  updated_at: 带时区的 ISO 8601 时间,
  accounts: [{
    id: "paper_main" | "paper_meeting" | "live_公开策略别名",
    mode: "paper" | "live",
    status: "未启动" | "运行中" | "已停手" | "事件窗口禁开新仓" | "已停止",
    equity: number | null,
    balance: number | null,
    daily_pnl: number | null,
    daily_loss_limit: 小数比例 | null,
    positions: [...],
    fills: [...],
    equity_curve: [...],
    updated_at?, name?, initial?, day?, day_start?,
    risk?, strategies?, strategy_enabled?
  }],
  decisions: {status, updated_at, version, meeting, symbols,
              global_size_factor, blackout_windows}
}
```

`id` 是公开的策略别名，**不得填写交易所账户号或 UID**。`name` 只使用角色/策略名。所有账户模式须与顶层相同；同一文件不得混入模拟盘和实盘。未启动账户的金额与日亏上限为 null，三个列表为空。已启动账户必须有真实 balance / equity / daily_loss_limit。

- `positions`：`symbol`（如 `ZEC-USDT-SWAP`）、`side`（1 多 / -1 空）、`qty`（币数量）、`entry`、`stop`、`take_profit`、`leverage`、`mark_price`、`unrealized_pnl`；可附 `margin`、`liquidation_price`、`entry_time`。未知价格和杠杆为 null，不能以入场价代替标记价。OKX 的合约张数需要在服务器端按合约面值转换成币数量。
- `fills`：`timestamp`、`symbol`、`side`、`kind`（open / close）、`qty`、`price`、`notional=qty×price`、`pnl`（开仓为 null，平仓为净已实现盈亏）。只包含已经执行的真实成交，不包含挂单和撤单。当前模拟程序每个开/平仓事件为一笔；未来实盘按实际 fill 逐笔导出，在服务器端去重，不发布原始订单 ID。
- `equity_curve`：`[{timestamp,equity}]`，每盘最多采样 500 个真实观测点。前端按时间合并，各盘有首个真实点后才开始绘制合计；两点之间沿用上一观测值，不补造首次观测之前的资金。任一已启动策略缺曲线时合计曲线显示“暂无”。
- `daily_pnl`：当前 UTC+7 日权益变动。可提供 `day` 和真实 `day_start`，前端据此随公共行情重估；没有日初基准则用快照 daily_pnl 和 equity 求基准。日期过期或基准缺失时不计算今日亏损。生产者须在 UTC+7 换日后更新日初值。
- `risk`：真实单笔风险、日亏上限、同向风险、固定或分档杠杆、blocked 标记。没有细项时为 null。`strategies` 仅允许 ema / breakout / mean_reversion 及公开数值参数；`strategy_enabled` 是只读状态。

计算口径：

- **BALANCE = 所有已启动的当前策略 balance 之和**，未启动策略不贡献虚构的零资金；旧四盘永不计入。
- 权益优先用公共最新价估算，模拟盘逐仓亏损按 `−margin` 封顶；缺行情时回退为真实快照 equity。已停止的当前策略保留余额和固定快照权益，停止不表示资产消失。
- 机器人总盈亏 = 合计权益 − 合计真实 initial。本金缺失则显示“—”，不猜测起始本金。浮盈列显示未封顶的 `side×qty×(mark−entry)`，未扣未来平仓费和资金费。
- **FILLS**：当前策略全部 fills 按成交时间归入当前 UTC+7 日，统计笔数并汇总实际成交额，开仓和平仓均计入。
- **SIZE**：当前所有持仓 `abs(qty×mark_price)` 之和；任一持仓无标记价时显示“—”。
- 日亏进度逐策略展示：`max(0,−daily_pnl/真实日初权益)`；剩余 = `max(0,daily_loss_limit−日亏比例)`，单位为百分点。达到上限或 blocked 时显示“已停手”。目标风控为 8%，实际上限取快照。
- 策略停止优先于停手，停手优先于事件窗口。事件窗口遵循 `[start,end)`；限定币种在面板列出，不代表其他币种也被禁开仓。开关不可点击，不从网页控制交易程序。

### 未来实盘推送

在**非美国服务器**使用只读密钥读取交易所数据，在服务器完成币数量换算、去重、UTC+7 日初基准和隐私清洗，输出完全相同的 JSON：顶层与各账户改为 `mode=live`，ID 使用 `live_` 加公开策略别名。

```bash
# 在生成/接收端对待发布文件校验，验证成功后再原子替换目标文件。
python3 tools/validate_account.py /tmp/account-next.json
```

`tools/validate_account.py` 只用 Python 标准库，读取 `account.schema.json` 所用的 JSON Schema 关键字并附加跨字段校验：模式一致、别名唯一、未启动金额为空、成交额一致、窗口起止有序、敏感内容过滤。该 schema 也可直接用于标准 Draft 2020-12 校验器（开启 date-time 格式验证）。不接受额外字段，错误信息不输出被拒绝原文。

密钥只存在于服务器的私有运行环境，**不得放进快照、README、config.js、浏览器请求或静态发布目录**。推送服务只替换公开快照；前端无需更换接口，会自动显示“实盘”。旧 snapshot.json / BT60 / 团队文件可继续保留为历史数据，不会覆盖首页实盘金额。实盘没有对应选填风控参数时界面显示“暂无”，不要沿用模拟盘参数冒充实盘设置。

## 决议与事件窗口

`make_snapshot.py` 从源目录 `decisions.json` 复制公开字段到 `paper/decisions.json`，同时嵌入 account.json，使首页读取同一批账户与决议。只发布 version、updated_at、meeting、symbols 的 bias/size_factor/note、global_size_factor、blackout_windows 的 start/end/symbols/reason。不复制 manual_orders、订单 ID、文件路径、运行错误或任意未知字段。

四种 bias 为 long / short / watch / ban，界面显示偏多 / 偏空 / 观察 / 禁开仓。单币分析显示对应币的 bias 与 note；参数面板列出公开决议、正在生效和未来事件窗口，过期窗口不冒充生效中。缺文件时 status=missing，界面显示暂无。公开文本先扫描完整值，再截断，发现敏感文本时置空。

## 保留的数据逻辑

生成器继续输出 `paper/snapshot.json`，供原模拟盘历史路由使用。读取 state.json、trades.csv、events.jsonl、equity.csv，不导入运行器。兼容传统 `engines` 格式和主力程序的 quantity / instId / net_pnl / target 字段。开仓只取实际 trade_opened，平仓合并 CSV 与 state 并去重；maker_placed 不算成交。

四个旧盘 paper_1h / paper_4h / paper_1h_aggr / paper_4h_aggr 固定为已停止，灰色历史卡与虚线曲线继续保留。旧盘缺风控时仅沿用原模拟程序默认值（1%、3 仓、3×、日亏 5%）并注明；新主力盘必须提供真实风控，不使用旧默认值。明确的 stopped 日志或停止状态优先；无明确状态时沿用两小时有效源数据时效判定。

`paper/team.json` 保留六角色的状态、当前任务、最新有效报告和评级，时间线支持角色+会议组合筛选。生成器读取 team/team_status.json、team/team_log.jsonl，按真实时间倒序取最近 200 条。阶段仅 P0–P7，状态仅工作中/已完成/待命，评级仅 A–F 或 null。标题最多 40 字、摘要和任务 200 字。对完整原记录（包括未知字段）过滤姓名黑名单、凭证关键字、长 token、邮箱、手机号和账户标签，命中则丢弃，不输出原文。坏行与缺团队文件不会伪造报告。

```bash
python3 tools/make_snapshot.py --team-only
python3 tools/make_snapshot.py --bt60-only
python3 tools/make_snapshot.py --source-root /只读源目录 --output paper/snapshot.json
# 统一账户输出可用 --account-output 指定；团队/回测也有独立输出参数，见 --help。
```

`paper/bt60.json` 保留 results/bt60_summary.csv、bt60_qualified.csv 的全部白名单指标、参数、样本内/样本外/全60天分段和真实合格记录。数据区间来自原 markdown，不按当前日期猜测。价差条件无历史数据，未用于回测。三段独立起算，收益不可相加；盈亏比为平均净盈利/平均净亏损绝对值，成本指标沿用原列名。完整成本和执行指标在每组中展开。

所有源文件先读取、验证再发布，单文件用临时文件原子替换；多个输出文件不是跨文件事务。前端失败时保留已有数据，显示延迟或读取失败并自动重试。

## 行情与指标

OKX 接口白名单：market/tickers、market/candles、public/funding-rate、public/open-interest。仅 GET，credentials=omit。全局队列至少间隔 150ms，最多 3 并发，保留请求合并、12 秒超时和限流冷却。行情 8 秒、K 线 / 资金费率 / 持仓量 / 快照 60 秒刷新；后台页面暂停网络轮询。

- 前 30 按 `volCcy24h×last` 估算 USDT 成交额排序；持仓额为 oiCcy×last，费率不年化。
- K 线 1H/4H 各取 300 根，主图含未收盘 K 线。
- EMA20/50/200 使用 SMA 种子，`α=2/(N+1)`；预热留空。
- RSI14 使用 Wilder 平滑；全平 50，无下跌 100，无上涨 0。
- MACD(12,26,9) 的柱为 DIF−DEA，不乘 2。
- 六条件只用 confirm=1 的已收盘 K 线，至少 51 根：突破前20根最高价；成交额≥前20根均值1.5倍；收盘位置≥0.7；EMA20>EMA50且收盘>EMA20；50<RSI14<70；MACD柱为正且增大。
- 前20/50根支撑阻力均排除信号自身。技术卡固定看1H，主图和底部分析随1H/4H切换。EMA200需要200根预热，300根种子与更长历史可能略有差异。

## 自测与截图

```bash
npm test
python3 -m unittest discover -s tests -v
python3 tools/validate_account.py
# 先运行上述 http.server；下面使用指定 Python Playwright 环境。
/home/box/.pw/bin/python tests/layout_browser.py
# 原有浏览器回归测试（可通过 NODE_PATH 指定 Playwright 安装位置）：
NODE_PATH=/tmp/crypto-panel-qa/node_modules node tests/browser_smoke.cjs
NODE_PATH=/tmp/crypto-panel-qa/node_modules PANEL_URL=http://127.0.0.1:8008/ node tests/team_browser.cjs
```

`layout_browser.py` 使用真实公共行情和发布快照，验证桌面1440、手机390×844及360/320无页面横向溢出、两列卡片、主屏切换、可折叠区、控制台与页面异常。另以请求拦截验证 live 模式、非空持仓/成交/决议和事件窗口，不更改发布 JSON。正式截图在测试场景之前生成，始终来自真实数据：

- `shot-desktop.png`：1440px 整页。
- `shot-mobile.png`：390×844 整页。

两张图已加入 .gitignore，**不在发布内容内**。测试示例只保留在 tests，截图不可混入部署包。

## 静态发布文件

发布仅包含 `index.html`、`config.js`、`assets/`、`paper/`、`.nojekyll`。不要发布 tools、tests、参考图、截图、私有源数据或运行环境文件。相对资源路径与 hash 路由支持项目子目录，无需构建。

图表固定为 jsDelivr 的 Lightweight Charts 4.2.2，保留 TradingView 归属。字体固定 CDN 版本 `@fontsource/press-start-2p@5.1.1` 和 `@fontsource/jetbrains-mono@5.1.2`，同时附本地 WOFF2 回退和许可证。CSP 仅允许同源静态资源、固定 CDN 资源及 www.okx.com 公共行情。
