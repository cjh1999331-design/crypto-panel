# MODI · AI 交易团队

手机优先的中文交易看板 v2。深蓝到深紫背景、发光毛玻璃卡片、六个自绘圆润 SVG 机器人，青 / 紫 / 品红强调色。行情直接读取 OKX 公共接口，交易数据只读取经过白名单清洗的同源 JSON。没有密钥、登录、账户号码或私有交易接口。

## 运行

```bash
cd /workspace/crypto-panel
python3 tools/make_snapshot.py
python3 tools/validate_account.py paper/account.json
python3 -m http.server 8008 --bind 127.0.0.1
```

打开 <http://127.0.0.1:8008/>。`config.js` 配置会议标的回退值 `symbol` 和 `startDate`，默认 `2026-11-02`。DAY 1 从该日期 UTC+7 零点开始，之后按 UTC+7 日界递增，实时时钟也使用 UTC+7。

首页顺序：

1. 六张团队卡：主席青、技术蓝、行业绿、新闻琥珀、风控红、操盘品红。手机两列；直接显示任务、报告摘要、时间和评级。
2. 交易视野：持仓币或信号币的 1H/4H K 线、EMA20/50/200、真实开平仓标记、实时 / 轮询 / 离线状态。默认最新持仓币，空仓时显示今日会议标的。
3. BALANCE 主力盘余额、模式标签和主力盘权益面积图。
4. 当前持仓、今日成交 / 成交额 / 持仓名义金额、最近成交、主力盘的日亏进度与只读开关状态。
5. 全市场扫描：全部主力币池、排序、信号/持仓筛选、48小时最近信号与当前持仓币；手机宽表可横向滑动。
6. 单币分析与 thresholds：量 / RSI / MACD、六条件、支撑阻力、会议结论、风险规则和实际策略参数。
7. 真实事件终端和可折叠的团队时间线、BT60、行情前 30、旧四盘历史。

保留 `#/market`（搜索排序）、`#/coin/ZEC-USDT-SWAP`（独立单币分析）、`#/paper`（原账户明细与历史曲线）路由。手机宽表仅在自身容器内左右滑动，扫描表支持自身滚动，全部币仍可查看。所有缺失数字显示“—”，缺失记录显示“暂无”；缺失策略目录显示“未启动”，不填入示例资金或价格。

## 统一账户快照：模拟盘 / 实盘共用

**首页唯一交易数据来源是 `paper/account.json`**，不从旧账户表拼当前总额。生成器目前固定 `mode=paper`，只读 `/workspace/crypto-bot/paper_main`；会议决议也在主力盘执行。目录不存在时发布未启动占位；目录存在但文件损坏或缺少必要数据时拒绝替换旧快照。不会写入 `/workspace/crypto-bot` 或执行交易程序。

契约入口（完整字段约束见 `tools/account.schema.json`）：

```text
{
  mode: "paper" | "live",
  source: 公开来源说明,
  updated_at: 带时区的 ISO 8601 时间,
  accounts: [{
    id: "paper_main" | "live_main",
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
    risk?, strategies?, enabled_strategies?, entry_mode_by_strategy?, strategy_enabled?, manual_status?
  }],
  decisions: {status, updated_at, version, meeting, symbols,
              global_size_factor, blackout_windows}
}
```

`id` 是公开的策略别名，**不得填写交易所账户号或 UID**。`name` 只使用角色/策略名。所有账户模式须与顶层相同；同一文件不得混入模拟盘和实盘。未启动账户的金额与日亏上限为 null，三个列表为空。已启动账户必须有真实 balance / equity / daily_loss_limit。

- `positions`：`symbol`（如 `ZEC-USDT-SWAP`）、`side`（1 多 / -1 空）、`qty`（币数量）、`entry`、`stop`、`take_profit`、`leverage`、`mark_price`、`unrealized_pnl`；可附 `margin`、`liquidation_price`、`entry_time`。未知价格和杠杆为 null，不能以入场价代替标记价。OKX 的合约张数需要在服务器端按合约面值转换成币数量。
- `fills`：`timestamp`、`symbol`、`side`、`kind`（open / close）、`qty`、`price`、`notional=qty×price`、`pnl`（开仓为 null，平仓为净已实现盈亏）。只包含已经执行的真实成交，不包含挂单和撤单。当前模拟程序每个开/平仓事件为一笔；未来实盘按实际 fill 逐笔导出，在服务器端去重，不发布原始订单 ID。
- `equity_curve`：`[{timestamp,equity}]`，每盘最多采样 500 个真实观测点。首页只绘制 paper_main 的真实观测点，主力盘缺曲线时显示“暂无”。旧四盘仍在历史区展示。
- `daily_pnl`：当前 UTC+7 日权益变动。可提供 `day` 和真实 `day_start`，前端据此随公共行情重估；常驻余额没有当日起始权益就明确显示基准缺失；策略区兼容快照 daily_pnl 口径。日期过期或基准缺失时不计算今日亏损。生产者须在 UTC+7 换日后更新日初值。
- `risk`：真实单笔风险、日亏上限、同向风险、固定或分档杠杆、blocked 标记。没有细项时为 null。`strategies` 仅允许 ema / breakout / mean_reversion 及公开数值参数；`strategy_enabled` 是只读状态。

计算口径：

- **常驻余额和 BALANCE = 当前现金余额 + 逐仓标记浮盈**，未启动策略不贡献虚构的零资金；旧四盘永不计入。
- 常驻余额优先使用浏览器 OKX WebSocket 的有效 tickers / mark-price 报价（45 秒时效），每次报价逐仓重算，亏损按每仓 `−margin` 封顶；缺实时价的仓位单独回退快照 mark_price，并显示回退来源。缺标记价才回退该账户 snapshot equity；空仓直接取快照 equity。已实现盈亏已计入 balance，不重复相加。当日金额 = 当前估值 − 各当前账户的当日起始权益，百分比除以同一基准；跨日或缺基准显示原因。已停止的当前策略保留余额和固定快照权益，停止不表示资产消失。
- 机器人总盈亏 = 主力盘权益 − 主力盘真实 initial。本金缺失则显示“—”，不猜测起始本金。浮盈列显示未封顶的 `side×qty×(mark−entry)`，未扣未来平仓费和资金费。
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

## 全市场扫描与主屏选币

`make_snapshot.py` 只读主力盘 `paper_main/scan.json`，白名单清洗后原子写入 `paper/scan.json`，包含 instruments、recent_signals、positions。源文件尚未生成时明确显示待更新；生成器不会启动或重启交易进程。扫描表覆盖当前全部交易币池，成交额来自原生1H实际 quote 总量，价差显示百分比；“当前信号”只用最新已收盘1H，预热/行情不足单独标注。最近信号展示48小时内的方向、开仓结果和未开仓原因，maker 待成交也有独立状态。

大K线下拉可选当前全部持仓币与信号币，默认最近开仓的持仓币；空仓时回退 team_status.json 的 meeting 标的，再回退 config.js。周期切换保留所选币。今日会议标的独立标注，主席卡同样标明会议标的，不自动加入交易币池。thresholds 的当前启用策略和 maker/taker 入场方式读取 account.json 的 enabled_strategies、entry_mode_by_strategy；旧主力 state 按其 strategies、entry_mode 恢复配置。

## 决议与事件窗口

`make_snapshot.py` 从源目录 `decisions.json` 复制公开字段到 `paper/decisions.json`，同时嵌入 account.json，使首页读取同一批账户与决议。只发布 version、updated_at、meeting、symbols 的 bias/size_factor/note、global_size_factor、blackout_windows 的 start/end/symbols/reason。不复制 manual_orders、订单 ID、文件路径、运行错误或任意未知字段。

四种 bias 为 long / short / watch / ban，界面显示偏多 / 偏空 / 观察 / 禁开仓。单币分析显示对应币的 bias 与 note；参数面板列出公开决议、正在生效和未来事件窗口，过期窗口不冒充生效中。缺文件时 status=missing，界面显示暂无。公开文本先扫描完整值，再截断，发现敏感文本时置空。

## 保留的数据逻辑

生成器继续输出 `paper/snapshot.json`，供原模拟盘历史路由使用。读取 state.json、trades.csv、events.jsonl、equity.csv，不导入运行器。兼容传统 `engines` 格式和主力程序的 quantity / instId / net_pnl / target 字段。开仓只取实际 trade_opened，平仓合并 CSV 与 state 并去重；maker_placed 不算成交。

四个旧盘 paper_1h / paper_4h / paper_1h_aggr / paper_4h_aggr 固定为已停止，灰色历史卡与虚线曲线继续保留。旧盘缺风控时仅沿用原模拟程序默认值（1%、3 仓、3×、日亏 5%）并注明；新主力盘必须提供真实风控，不使用旧默认值。明确的 stopped 日志或停止状态优先；无明确状态时沿用两小时有效源数据时效判定。

`paper/team.json` 保留六角色的状态、当前任务、最新有效报告和评级，时间线支持角色+会议组合筛选。生成器读取 team/team_status.json、team/team_log.jsonl，按真实时间倒序取最近 200 条。阶段仅 P0–P7，状态仅工作中/已完成/待命/离线，评级为 A–F 加可选 + / -（如 A-、B+）或 null，保留符号、按字母着色。非法记录跳过，warnings.details 记录字段名及日志行号/固定角色名与原因代码，不包含原文。标题最多 40 字、摘要和任务 200 字。对完整原记录（包括未知字段）过滤姓名黑名单、凭证关键字、长 token、邮箱、手机号和账户标签，命中则丢弃，不输出原文。坏行与缺团队文件不会伪造报告。

```bash
python3 tools/make_snapshot.py --team-only
python3 tools/make_snapshot.py --bt60-only
python3 tools/make_snapshot.py --source-root /只读源目录 --output paper/snapshot.json
# 统一账户输出可用 --account-output 指定；团队/回测也有独立输出参数，见 --help。
```

`paper/bt60.json` 保留 results/bt60_summary.csv、bt60_qualified.csv 的全部白名单指标、参数、样本内/样本外/全60天分段和真实合格记录。数据区间来自原 markdown，不按当前日期猜测。价差条件无历史数据，未用于回测。三段独立起算，收益不可相加；盈亏比为平均净盈利/平均净亏损绝对值，成本指标沿用原列名。完整成本和执行指标在每组中展开。

所有源文件先读取、验证再发布，单文件用临时文件原子替换；多个输出文件不是跨文件事务。前端失败时保留已有数据，显示延迟或读取失败并自动重试。

## 行情与指标

OKX 接口白名单：market/tickers、market/candles、public/funding-rate、public/open-interest。仅 GET，credentials=omit。全局队列至少间隔 150ms，最多 3 并发，保留请求合并、12 秒超时和限流冷却。REST 行情 8 秒、K 线 / 资金费率 / 持仓量 / 快照 60 秒刷新。浏览器同时连接 `wss://ws.okx.com:8443/ws/v5/business` 的 candle1H / candle4H、`/ws/v5/public` 的 tickers / mark-price，订阅随选币与持仓变化重建。每连接指数退避 1 / 2 / 4 秒，默认连续 4 次失败回退 REST，不伪装实时；心跳、首包超时和行情停滞会断线重连。后台页关闭连接、停止轮询并暂停动画，恢复时重新同步。

- 前 30 按 `volCcy24h×last` 估算 USDT 成交额排序；持仓额为 oiCcy×last，费率不年化。
- K 线 1H/4H 各取 300 根，主图含未收盘 K 线。
- EMA20/50/200 使用 SMA 种子，`α=2/(N+1)`；预热留空。
- RSI14 使用 Wilder 平滑；全平 50，无下跌 100，无上涨 0。
- MACD(12,26,9) 的柱为 DIF−DEA，不乘 2。
- 六条件只用 confirm=1 的已收盘 K 线，至少 51 根：突破前20根最高价；成交额≥前20根均值1.5倍；收盘位置≥0.7；EMA20>EMA50且收盘>EMA20；50<RSI14<70；MACD柱为正且增大。
- 前20/50根支撑阻力均排除信号自身。技术卡固定看1H，主图和底部分析随1H/4H切换。EMA200需要200根预热，300根种子与更长历史可能略有差异。

## v2 状态与动态效果

所有角色动作来自公开状态：待命呼吸 / 眨眼；工作中打字、轻晃头、屏幕扫光、光环和边框流光；已完成显示勾；team.json 显式离线，或源 status.updated_at / generated_at 任一超过 config.js 的 offlineMinutes（默认 15 分钟），停止动作并显示原因与 zzz。首次读取 team_log 静默；之后真正新增的记录触发挥手、文件传递与通知，重排 / 旧记录回流不重播。新开仓事件触发操盘跳跃，止损平仓 / 日停手事件触发风控举牌；离线角色不播放动作。背景光斑只在存在有效行情或新鲜团队状态时流动。

生成器只读 paper_main/events.jsonl，并读取存在时的 alerts.jsonl 最近 100 行，按时间合并后保留最新 300 条到 paper/events.json；不读取会议账户事件。交易事件只允许 ts / type / coin / strategy / direction / price / reason，类型、策略、原因均固定词表；币种格式校验，价格只接受有限正数；币池数量只从非负整数生成。不复制原错误、任意配置文本、文件路径、内部 ID 或凭证。未知类型跳过，未知原因显示“原因未公开”。终端首载直接显示旧事件，新增逐字显示；无记录显示“暂无事件”，读取失败保留已有内容并说明。

异动输入只读取 ts / symbol / type / value / detail / source_url；type、value、detail 清洗并合成最多 80 字短句，公开类型为“异动”，日志终端以琥珀色显示。source_url 只允许无凭证的 HTTPS 公开链接，拒绝本机、私网和内部域名；不存在 alerts.jsonl 时照常生成。

paper_main 的 state.json 或 scan.json 中 manual_status 转成匿名会议挂单表，只含币、方向、限价、止损、止盈、有效期和 pending / filled / expired / rejected / cancelled 状态。实盘进程区显示该表，缺字段显示“—”，缺数据隐藏；strategy=manual 的持仓标“会议单”。不公开订单 ID、备注和运行器原因。

prefers-reduced-motion 关闭所有动画、流光、数字滚动和逐字效果，内容直接显示，数值变化仍以颜色提示。hardwareConcurrency ≤ 4、deviceMemory ≤ 4 或不支持 backdrop-filter 时，取消模糊并减少光斑。CSS 动画仅使用 transform / opacity。

## 自测与录屏

```bash
npm test
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/validate_account.py paper/account.json
# 先运行 http.server，使用指定 Python Playwright：
PANEL_URL=http://127.0.0.1:8008/ /home/box/.pw/bin/python tests/layout_browser.py
PANEL_URL=http://127.0.0.1:8008/ /home/box/.pw/bin/python tests/scan_browser.py
```

layout_browser.py 调用 v2_browser.py，先在隔离响应中验证新记录 / WebSocket 报价 / 动画 / reduced-motion / 离线，再用真实快照和公共行情生成正式产物。测试数据不写 paper，也不出现在首页截图和首页视频。真实环境验证 1440 桌面、390 / 360 / 320 手机无页面横向溢出、滚动时右上角余额常驻、1H / 4H、展开区和市场 / 历史路由。区分应用 console.error / pageerror 与 Chromium 自行记录的外部网络错误，并如实报告；WebSocket 失败时首页显示轮询或离线和快照标记价来源。

- shot-mobile.png：390×844 首屏；shot-mobile-full.png：390px 整页；shot-desktop.png：1440px 整页。
- rec-mobile.webm：首页 390×844 的真实数据视频，10 秒。
- rec-demo.webm：独立 tests/demo.html，390×844、10 秒，始终标注“演示数据”；从 tests/fixtures/demo.json 读取六角色的八组演示场景，支持重新播放，不进入首页导航。

截图和视频均已加入 .gitignore。测试目录与录屏不得进入静态发布包。

## 静态发布文件

发布仅包含 `index.html`、`config.js`、`assets/`、`paper/`、`.nojekyll`。不要发布 tools、tests、参考图、截图、私有源数据或运行环境文件。相对资源路径与 hash 路由支持项目子目录，无需构建。

图表固定为 jsDelivr 的 Lightweight Charts 4.2.2，保留 TradingView 归属。正文字体固定为 CDN `@fontsource-variable/inter@5.1.0`，中文回退 PingFang SC / Microsoft YaHei / Noto Sans SC；数字为本地 JetBrains Mono（5.1.2）和 tabular-nums。CSP 仅允许同源静态资源、固定 CDN 资源、www.okx.com REST 与指定 OKX 公共 WebSocket。
