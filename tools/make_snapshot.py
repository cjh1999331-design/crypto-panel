#!/usr/bin/env python3
"""从本地模拟盘生成可公开的白名单快照。只用标准库，不导入或执行交易程序。"""
import argparse
import csv
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ACCOUNTS = [('paper_4h', '4 小时 · 稳健'), ('paper_1h', '1 小时 · 稳健'),
            ('paper_4h_aggr', '4 小时 · 进取'), ('paper_1h_aggr', '1 小时 · 进取')]
# paper_trade.py 对旧 state 的默认值；不从任意配置文件复制内容。
LEGACY_RISK = dict(risk_per_trade=.01, max_positions=3, leverage=3., daily_loss_limit=.05)
SYMBOL = re.compile(r'^[A-Z0-9]+-USDT-SWAP$')
REASONS = {'signal', 'stop', 'stop_live', 'liquidated', 'end', 'end_of_data', 'take_profit'}
# 已于 2026-11-02 20:31 UTC+7 停止，保留历史曲线与成交。
ARCHIVED_ACCOUNTS = {account_id for account_id, _ in ACCOUNTS}
TEAM_ROLES = dict(umi='umi 主席', tech='技术', industry='行业', news='新闻政策', risk='风控', trader='操盘')
TEAM_STATUSES = {'工作中', '已完成', '待命'}
SENSITIVE = re.compile(r'\u9648\u5bb6\u8c6a|[A-Za-z0-9+/]{24,}={0,2}|api[_-]?key|secret|passphrase|'
                       r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:账户|账号|account)\s*[:：=]|\b1[3-9]\d{9}\b', re.I)


def sensitive(value):
    """扫描原始完整记录（包括未公开字段及键名），不记录原文。"""
    if isinstance(value, str):
        return bool(SENSITIVE.search(value))
    if isinstance(value, dict):
        return any(sensitive(k) or sensitive(v) for k, v in value.items())
    if isinstance(value, list):
        return any(sensitive(v) for v in value)
    return False


def team_ts(value):
    if not isinstance(value, str) or not re.match(r'^\d{4}-\d{2}-\d{2}T', value):
        raise ValueError('团队时间格式无效')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('团队时间缺少时区')
    return dt.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def team_text(row, key, limit=None, empty=False):
    value = row.get(key)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError('团队文本字段无效')
    return value[:limit] if limit else value


def clean_report(row):
    if not isinstance(row, dict) or row.get('grade') not in (None, 'A', 'B', 'C', 'D', 'E', 'F'):
        raise ValueError('团队评级无效')
    return dict(ts=team_ts(row.get('ts')), title=team_text(row, 'title', 40),
                summary=team_text(row, 'summary', 200), grade=row.get('grade'))


def build_team(team_root, now=None):
    root = Path(team_root)
    warnings = dict(invalid_log=0, invalid_status=0, redacted_log=0, redacted_status=0,
                    duplicate_log=0, missing_files=0)
    status = dict(updated_at=None, meeting=None, phase=None, roles={})
    logs = []
    try:
        with (root / 'team_log.jsonl').open(encoding='utf-8') as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except ValueError:
                    warnings['invalid_log'] += 1
                    continue
                if sensitive(raw):
                    warnings['redacted_log'] += 1
                    continue
                try:
                    row = clean_report(raw)
                    if raw.get('role') not in TEAM_ROLES or raw.get('status') not in TEAM_STATUSES or raw.get('phase') not in {f'P{i}' for i in range(8)}:
                        raise ValueError('团队枚举无效')
                    row.update(role=raw['role'], status=raw['status'], phase=raw['phase'], meeting=team_text(raw, 'meeting'))
                    if 'id' in raw:
                        row['id'] = team_text(raw, 'id')
                    logs.append(row)
                except (ValueError, TypeError, OverflowError):
                    warnings['invalid_log'] += 1
    except FileNotFoundError:
        warnings['missing_files'] += 1
    except (OSError, UnicodeError):
        warnings['invalid_log'] += 1
    unique, anonymous = {}, []
    for row in logs:
        if 'id' not in row:
            anonymous.append(row)
        else:
            previous = unique.get(row['id'])
            if previous:
                warnings['duplicate_log'] += 1
            if previous is None or row['ts'] >= previous['ts']:
                unique[row['id']] = row
    try:
        raw = json.loads((root / 'team_status.json').read_text(encoding='utf-8'))
        if not isinstance(raw, dict) or not isinstance(raw.get('roles'), dict):
            raise ValueError('团队状态无效')
        metadata = {k: v for k, v in raw.items() if k != 'roles'}
        if sensitive(metadata):
            warnings['redacted_status'] += 1
            raw = {'roles': {}}
        else:
            # 初始待命文件允许三个元数据字段全部为空。
            if any(raw.get(k) is not None for k in ('updated_at', 'meeting', 'phase')):
                if raw.get('phase') not in {f'P{i}' for i in range(8)}:
                    raise ValueError('团队阶段无效')
                status.update(updated_at=team_ts(raw.get('updated_at')), meeting=team_text(raw, 'meeting'), phase=raw['phase'])
        for role, record in raw['roles'].items():
            if sensitive(role) or sensitive(record):
                warnings['redacted_status'] += 1
                continue
            try:
                if role not in TEAM_ROLES or not isinstance(record, dict) or record.get('status') not in TEAM_STATUSES:
                    raise ValueError('团队角色状态无效')
                status['roles'][role] = dict(name=TEAM_ROLES[role], status=record['status'],
                    task=team_text(record, 'task', 200, empty=True),
                    last_report=clean_report(record['last_report']) if record.get('last_report') is not None else None)
            except (ValueError, TypeError, OverflowError):
                warnings['invalid_status'] += 1
    except FileNotFoundError:
        warnings['missing_files'] += 1
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError):
        warnings['invalid_status'] += 1
    return dict(schema_version=1, generated_at=(now or datetime.now(timezone.utc)).isoformat(), status=status,
                log=sorted([*anonymous, *unique.values()], key=lambda r: r['ts'], reverse=True)[:200], warnings=warnings)


def numeric(value, default=None):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def iso(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    except ValueError:
        return None


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def downsample(points, limit=500):
    """等距取样，保留首尾，时间顺序不变。"""
    if len(points) <= limit:
        return points
    return [points[round(i * (len(points) - 1) / (limit - 1))] for i in range(limit)]


def clean_position(symbol, data):
    if not SYMBOL.fullmatch(symbol) or not isinstance(data, dict):
        raise ValueError('无效持仓')
    result = {'symbol': symbol}
    for key in ('side', 'qty', 'entry', 'stop', 'margin', 'liquidation_price', 'leverage', 'take_profit', 'mark_price', 'unrealized_pnl'):
        result[key] = numeric(data.get(key, data.get({'qty': 'quantity', 'liquidation_price': 'liq', 'take_profit': 'target'}.get(key, key))))
    if result['side'] not in (-1, 1) or any(result[k] is None or result[k] <= 0 for k in ('qty', 'entry', 'stop')):
        raise ValueError('持仓数值不完整')
    result['side'] = int(result['side'])
    if result['margin'] is None or result['margin'] < 0:
        raise ValueError('持仓保证金不完整')
    result['entry_time'] = iso(data.get('entry_time'))
    return result


def clean_trade(data, kind='close'):
    symbol = data.get('symbol', data.get('instId', ''))
    timestamp = iso(data.get('entry_time') if kind == 'open' else data.get('exit_time'))
    if not SYMBOL.fullmatch(symbol) or not timestamp:
        return None
    side = numeric(data.get('side'))
    result = dict(symbol=symbol, kind=kind, timestamp=timestamp, side=int(side) if side in (-1, 1) else None)
    for key in ('qty', 'entry', 'exit', 'pnl'):
        result[key] = numeric(data.get(key, data.get({'qty': 'quantity', 'pnl': 'net_pnl'}.get(key, key))))
    result['entry_time'] = iso(data.get('entry_time'))
    result['reason'] = data.get('reason') if data.get('reason') in REASONS else 'other'
    if kind == 'open':
        result['exit'] = result['pnl'] = None
    return result


def build_account(root, account_id, name, now=None):
    directory = root / account_id
    state_path = directory / 'state.json'
    raw = state_path.read_bytes()
    state = json.loads(raw)
    balance = numeric(state.get('balance'))
    if balance is None or not isinstance(state.get('engines'), dict):
        raise ValueError('模拟盘状态不完整')
    positions = [clean_position(symbol, engine['position']) for symbol, engine in state['engines'].items() if engine.get('position')]
    marked_equity = balance
    for position in positions:
        mark = numeric(state.get('prices', {}).get(position['symbol']))
        if mark is None or mark <= 0:
            raise ValueError('持仓标记价格缺失')
        marked_equity += max(-position['margin'], position['side'] * position['qty'] * (mark - position['entry']))
        position['mark_price'] = mark
        position['unrealized_pnl'] = position['side'] * position['qty'] * (mark - position['entry'])
    risk = {key: numeric(state.get(key), default if account_id in dict(ACCOUNTS) else None) for key, default in LEGACY_RISK.items()}
    # 主力盘按同向风险额度与成交额分档限制仓位，不伪造固定仓数或杠杆。
    same_direction = numeric(state.get('same_direction_risk_limit'))
    tiers = state.get('leverage_tiers')
    dynamic = (same_direction is not None and 0 < same_direction <= 1 and isinstance(tiers, dict) and
               all(numeric(tiers.get(k), 0) > 0 for k in ('turnover_gte_50000000', 'turnover_lt_50000000', 'threshold_usdt')))
    if any(risk[k] is None or risk[k] <= 0 for k in ('risk_per_trade', 'daily_loss_limit')) or risk['daily_loss_limit'] > 1:
        raise ValueError('模拟盘风控参数不完整')
    if any((risk[k] is None and not dynamic) or (risk[k] is not None and risk[k] <= 0) for k in ('max_positions', 'leverage')):
        raise ValueError('模拟盘仓位或杠杆参数不完整')
    if dynamic:
        risk['same_direction_risk_limit'] = same_direction
        risk['leverage_tiers'] = {k: numeric(tiers[k]) for k in ('turnover_gte_50000000', 'turnover_lt_50000000', 'threshold_usdt')}
    risk['max_positions'] = int(risk['max_positions']) if risk['max_positions'] is not None else None
    risk['blocked'] = state.get('blocked') is True
    risk['legacy_defaults'] = account_id in ARCHIVED_ACCOUNTS and any(numeric(state.get(key)) is None for key in LEGACY_RISK)
    trades = {}
    # state 比 trades.csv 更早原子写入；合并去重，保留已写入 state 的最新平仓。
    closed = read_csv(directory / 'trades.csv')
    closed += [dict(t, symbol=s) for s, engine in state['engines'].items() for t in engine.get('trades', [])]
    for row in closed:
        trade = clean_trade(row)
        if trade:
            trades[(trade['symbol'], trade['kind'], trade['timestamp'], trade['entry_time'])] = trade
    updated = None
    lifecycle = None
    # events 只提取开仓成交和 poll 时间；不公开日志文本、异常或任意嵌套字段。
    with (directory / 'events.jsonl').open(encoding='utf-8') as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # 正在追加的一行可能还未写完
            if not isinstance(event, dict):
                continue
            if event.get('event') in ('started', 'stopped') and iso(event.get('timestamp')):
                candidate = (iso(event['timestamp']), event['event'])
                if lifecycle is None or candidate[0] >= lifecycle[0]:
                    lifecycle = candidate
            if event.get('event') == 'poll' and iso(event.get('timestamp')):
                timestamp = iso(event['timestamp'])
                updated = max(updated or timestamp, timestamp)
            if event.get('event') == 'trade_opened':
                trade = clean_trade(event, 'open')
                if trade:
                    trades[(trade['symbol'], trade['kind'], trade['timestamp'], trade['entry_time'])] = trade
    curve = {}
    source_times = []
    for key in ('updated_at', 'timestamp', 'last_update'):
        if iso(state.get(key)):
            source_times.append(datetime.fromisoformat(iso(state[key]).replace('Z', '+00:00')))
    if not source_times:
        source_times.append(datetime.fromtimestamp(state_path.stat().st_mtime, timezone.utc))
    for row in read_csv(directory / 'equity.csv'):
        timestamp, equity = iso(row.get('timestamp')), numeric(row.get('equity'))
        if timestamp and equity is not None:
            source_times.append(datetime.fromisoformat(timestamp.replace('Z', '+00:00')))
            curve[timestamp] = dict(timestamp=timestamp, equity=equity)
            updated = max(updated or timestamp, timestamp)
    # 防止读取中 state 已被替换，失败时保留现有快照。
    if state_path.read_bytes() != raw:
        raise ValueError('读取期间模拟盘已更新，请重新生成')
    stopped = (account_id in ARCHIVED_ACCOUNTS or (lifecycle is not None and lifecycle[1] == 'stopped')
               or state.get('status') == '已停止' or ((now or datetime.now(timezone.utc)) - max(source_times)).total_seconds() > 7200)
    return dict(id=account_id, name=name, status='已停止' if stopped else '运行中', balance=balance, marked_equity=marked_equity,
                positions=positions, trades=sorted(trades.values(), key=lambda t: t['timestamp'], reverse=True),
                equity=downsample([curve[t] for t in sorted(curve)]), risk=risk,
                updated_at=updated, initial=numeric(state.get('initial')),
                day=state.get('day') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(state.get('day', ''))) else None,
                day_start=numeric(state.get('day_start')))


def build_snapshot(source_root, now=None):
    generated = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    root = Path(source_root)
    names = dict(ACCOUNTS, paper_main='主力盘', paper_meeting='交易室盘')
    directories = sorted(p for p in root.glob('paper_*') if p.is_dir() and re.fullmatch(r'paper_[a-z0-9_]+', p.name))
    directories.sort(key=lambda p: (list(names).index(p.name) if p.name in names else len(names), p.name))
    if not directories:
        raise ValueError('没有模拟盘目录')
    return dict(schema_version=1, generated_at=generated,
                accounts=[build_account(root, p.name, names.get(p.name, '扩展模拟盘 ' + str(i + 1)), now=now) for i, p in enumerate(directories)])


def public_text(value, limit=200):
    return value[:limit] if isinstance(value, str) and not sensitive(value) else None


def build_decisions(root):
    """只公开会议摘要；不发布手工订单、ID、文件路径或运行器异常。"""
    path = Path(root) / 'decisions.json'
    if not path.exists():
        return dict(status='missing', updated_at=None, meeting=None, version=None,
                    symbols={}, blackout_windows=[], global_size_factor=None)
    raw = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise ValueError('决议格式无效')
    symbols = {}
    for symbol, rule in raw.get('symbols', {}).items():
        if not SYMBOL.fullmatch(symbol) or not isinstance(rule, dict):
            continue
        if rule.get('bias') not in ('long', 'short', 'watch', 'ban'):
            continue
        factor = numeric(rule.get('size_factor'))
        symbols[symbol] = dict(bias=rule['bias'], note=public_text(rule.get('note')),
                               size_factor=factor if factor is not None and 0 <= factor <= 1 else None)
    windows = []
    for row in raw.get('blackout_windows', []):
        start, end = iso(row.get('start')), iso(row.get('end'))
        targets = row.get('symbols')
        if start and end and start < end and isinstance(targets, list):
            targets = [s for s in targets if isinstance(s, str) and (s == '*' or SYMBOL.fullmatch(s))]
            if targets:
                windows.append(dict(start=start, end=end, symbols=list(dict.fromkeys(targets)), reason=public_text(row.get('reason'))))
    factor = numeric(raw.get('global_size_factor'))
    version = raw.get('version')
    version = str(version) if isinstance(version, (str, int)) and not isinstance(version, bool) else None
    return dict(status='active', updated_at=iso(raw.get('updated_at')), meeting=public_text(raw.get('meeting'), 80),
                version=public_text(version, 40), symbols=symbols, blackout_windows=windows,
                global_size_factor=factor if factor is not None and 0 <= factor <= 1 else None)


def build_public_accounts(root, now=None, legacy=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    day = datetime.fromtimestamp(now.timestamp() + 7 * 3600, timezone.utc).date().isoformat()
    decisions = build_decisions(root)
    accounts = []
    for account_id, name in [('paper_main', '主力策略'), ('paper_meeting', '会议策略')]:
        directory = root / account_id
        if not directory.exists():
            accounts.append(dict(id=account_id, name=name, mode='paper', status='未启动', equity=None,
                balance=None, daily_pnl=None, daily_loss_limit=None, positions=[], fills=[], equity_curve=[],
                updated_at=None, initial=None, day=None, day_start=None, risk=None, strategies={}, strategy_enabled=None))
            continue
        account = next((a for a in (legacy or {}).get('accounts', []) if a['id'] == account_id), None)
        account = account or build_account(root, account_id, name, now)
        raw = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
        status = account['status']
        if status == '运行中' and account['day'] == day and account['risk']['blocked']:
            status = '已停手'
        fills = []
        for trade in account['trades']:
            fill_price = trade['entry'] if trade['kind'] == 'open' else trade['exit']
            if trade['qty'] is None or trade['qty'] <= 0 or fill_price is None or fill_price <= 0:
                continue
            fills.append(dict(timestamp=trade['timestamp'], symbol=trade['symbol'], side=trade['side'],
                kind=trade['kind'], qty=trade['qty'], price=fill_price, notional=trade['qty'] * fill_price, pnl=trade['pnl']))
        strategies = {}
        for strategy, parameters in raw.get('strategies', {}).items():
            if strategy in ('ema', 'breakout', 'mean_reversion') and isinstance(parameters, dict):
                strategies[strategy] = {k: numeric(v) for k, v in parameters.items()
                                        if k in ('fast', 'slow', 'lookback', 'volume', 'rsi', 'trend') and numeric(v) is not None}
        accounts.append(dict(id=account_id, name=name, mode='paper', status=status, equity=account['marked_equity'],
            balance=account['balance'], daily_pnl=(account['marked_equity'] - account['day_start'])
            if account['day'] == day and account['day_start'] is not None else None,
            daily_loss_limit=account['risk']['daily_loss_limit'], positions=account['positions'], fills=fills,
            equity_curve=account['equity'], updated_at=iso(raw.get('updated_at')) or account['updated_at'], initial=account['initial'],
            day=account['day'], day_start=account['day_start'], risk=account['risk'], strategies=strategies,
            strategy_enabled=status not in ('已停止',)))
    return dict(mode='paper', source='本地模拟盘公开快照', updated_at=now.isoformat().replace('+00:00', 'Z'),
                accounts=accounts, decisions=decisions)


def write_snapshot(snapshot, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8')
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


# 固定白名单，避免将任意研究文件内容复制到公开面板。
BT60_NUMERIC = ('trades', 'win_rate_pct', 'payoff_ratio', 'profit_factor', 'return_pct',
    'max_drawdown_pct', 'fees', 'slippage', 'funding', 'gross_pnl', 'total_cost',
    'gross_winning_pnl', 'isolated_insurance_credit', 'cost_over_gross_winning_pct',
    'cost_over_abs_gross_pct', 'cost_over_initial_pct', 'liquidations', 'daily_halt_days',
    'average_daily_candidates', 'final_equity', 'realized_losses_over_3pct',
    'max_trade_loss_pct_of_entry_equity', 'reconciliation_error')
BT60_STRATEGIES = {'ema': 'EMA 趋势', 'breakout': '突破放量', 'mean_reversion': '均值回归'}
BT60_PARAMETERS = {'fast', 'slow', 'lookback', 'volume', 'rsi', 'trend'}


def build_bt60(results_root):
    root = Path(results_root)
    def clean(row):
        code, timeframe, segment = (row.get(k) for k in ('strategy_code', 'timeframe', 'segment'))
        if code not in BT60_STRATEGIES or timeframe not in ('15m', '1H', '4H') or segment not in ('选参段', '样本内', '样本外', '全60天'):
            raise ValueError('回测分类不完整')
        parameters = json.loads(row.get('parameters') or '{}')
        if not isinstance(parameters, dict):
            raise ValueError('回测参数格式错误')
        return dict(strategy=BT60_STRATEGIES[code], strategy_code=code, timeframe=timeframe, segment=segment,
                    parameters={k: numeric(v) for k, v in parameters.items() if k in BT60_PARAMETERS},
                    **{k: numeric(row.get(k)) for k in BT60_NUMERIC})
    rows = [clean(r) for r in read_csv(root / 'bt60_summary.csv')]
    qualified = [clean(r) for r in read_csv(root / 'bt60_qualified.csv')]
    if not rows:
        raise ValueError('回测汇总为空')
    key = lambda r: (r['strategy_code'], r['timeframe'], r['segment'])
    qualified_keys = {key(r) for r in qualified}
    summary_by_key = {key(r): r for r in rows}
    if len(summary_by_key) != len(rows) or any(summary_by_key.get(key(q)) != q for q in qualified):
        raise ValueError('合格组合与汇总不一致')
    for row in rows:
        row['qualified'] = key(row) in qualified_keys
        row['qualified_combination'] = any(row['strategy_code'] == q['strategy_code'] and row['timeframe'] == q['timeframe'] for q in qualified)
    report = (root / 'bt60_summary.md').read_text(encoding='utf-8')
    generated = re.search(r'生成时间[：:]\s*([0-9T:.+Z-]+)', report)
    periods = re.findall(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}),\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\)', report)
    # 区间只取报告开头的整体与样本外区间，不复制正文或路径。
    return dict(schema_version=1, generated_at=iso(generated[1].rstrip('.')) if generated else None,
                period={'start': iso(periods[0][0]), 'end': iso(periods[0][1]), 'timezone': 'UTC'} if periods else None,
                out_of_sample={'start': iso(periods[1][0]), 'end': iso(periods[1][1]), 'timezone': 'UTC'} if len(periods) > 1 else None,
                note='价差条件无历史数据，未用于回测', rows=rows, qualified=qualified,
                sources=['bt60_summary.csv', 'bt60_qualified.csv', 'bt60_summary.md'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path('/workspace/crypto-bot'))
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent / 'paper/snapshot.json')
    parser.add_argument('--results-root', type=Path, help='回测 CSV 所在目录，默认 source-root/results')
    parser.add_argument('--bt60-output', type=Path, help='默认在快照输出旁生成 bt60.json')
    parser.add_argument('--bt60-only', action='store_true', help='只更新回测公开数据')
    parser.add_argument('--account-output', type=Path, help='统一账户快照，默认 account.json')
    parser.add_argument('--team-only', action='store_true', help='只更新团队公开数据')
    parser.add_argument('--team-root', type=Path, help='团队源目录，默认 source-root/team')
    parser.add_argument('--team-output', type=Path, help='默认在快照输出旁生成 team.json')
    args = parser.parse_args()
    try:
        team = build_team(args.team_root or args.source_root / 'team')
        if args.team_only:
            write_snapshot(team, args.team_output or args.output.with_name('team.json'))
            print('已生成团队公开数据。')
            return
        bt60 = build_bt60(args.results_root or args.source_root / 'results')
        snapshot = None if args.bt60_only else (build_snapshot(args.source_root) if any(args.source_root.glob('paper_*')) else dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(), accounts=[]))
        if snapshot is not None:
            public = build_public_accounts(args.source_root, legacy=snapshot)
            from validate_account import validate_account
            validate_account(public)
            write_snapshot(snapshot, args.output)
            write_snapshot(public, args.account_output or args.output.with_name('account.json'))
            write_snapshot(public['decisions'], args.output.with_name('decisions.json'))
        write_snapshot(bt60, args.bt60_output or args.output.with_name('bt60.json'))
        if not args.bt60_only:
            write_snapshot(team, args.team_output or args.output.with_name('team.json'))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # 控制台也不复制可能包含任意原始内容的解析异常。
        parser.exit(1, f'快照未更新：读取或校验失败（{type(exc).__name__}），请检查模拟盘与回测源文件后重试。\n')
    print('已生成公开快照、团队与 BT60 回测数据。')


if __name__ == '__main__':
    main()
