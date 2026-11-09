#!/usr/bin/env python3
"""从本地模拟盘生成可公开的白名单快照。只用标准库，不导入或执行交易程序。"""
import argparse
import csv
import json
import math
import os
import re
import ipaddress
from urllib.parse import urlsplit
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
TEAM_ROLES = dict(gork='gork 总指挥', claude='claude', codex='Codex', grok='Grok')
ROLE_ALIASES = {'umi': 'gork'}  # 旧日志/状态里的 umi 映射为 gork，界面不再显示 umi
RETIRED_TEAM_ROLES = {'tech', 'industry', 'news', 'risk', 'trader'}
TEAM_STATUSES = {'工作中', '已完成', '待命', '离线'}


def canonical_team_role(role):
    """Map legacy aliases; return (canonical_or_original, silent_skip)."""
    if not isinstance(role, str):
        return role, False
    if role in RETIRED_TEAM_ROLES:
        return None, True
    return ROLE_ALIASES.get(role, role), False
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


class TeamFieldError(ValueError):
    def __init__(self, field, reason='invalid'):
        self.field, self.reason = field, reason
        super().__init__(field)


def team_ts(value, field='ts'):
    if not isinstance(value, str) or not re.match(r'^\d{4}-\d{2}-\d{2}T', value):
        raise TeamFieldError(field, 'invalid_timestamp')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise TeamFieldError(field, 'missing_timezone')
        return dt.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    except (ValueError, OverflowError) as exc:
        if isinstance(exc, TeamFieldError): raise
        raise TeamFieldError(field, 'invalid_timestamp') from None


def team_text(row, key, limit=None, empty=False):
    value = row.get(key)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise TeamFieldError(key, 'invalid_text')
    return value[:limit] if limit else value


def team_enum(row, key, choices):
    if not isinstance(row.get(key), str) or row[key] not in choices:
        raise TeamFieldError(key, 'invalid_enum')
    return row[key]


def clean_report(row):
    if not isinstance(row, dict): raise TeamFieldError('last_report', 'expected_object')
    grade = row.get('grade')
    if grade is not None and (not isinstance(grade, str) or not re.fullmatch(r'[A-F][+-]?', grade)):
        raise TeamFieldError('grade', 'expected_A_F_optional_sign')
    return dict(ts=team_ts(row.get('ts')), title=team_text(row, 'title', 40),
                summary=team_text(row, 'summary', 200), grade=grade)


def build_team(team_root, now=None):
    root = Path(team_root)
    warnings = dict(invalid_log=0, invalid_status=0, redacted_log=0, redacted_status=0,
                    duplicate_log=0, missing_files=0)
    def warn(counter, field, reason, **location):
        warnings[counter] += 1
        warnings.setdefault('details', []).append(dict(source='team_log.jsonl' if counter.endswith('log') else 'team_status.json',
                                                      field=field, reason=reason, **location))
    status = dict(updated_at=None, meeting=None, phase=None, roles={})
    logs = []
    try:
        with (root / 'team_log.jsonl').open(encoding='utf-8') as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip(): continue
                try:
                    raw = json.loads(line)
                except ValueError:
                    warn('invalid_log', 'json', 'malformed_json', line=line_number); continue
                if not isinstance(raw, dict):
                    warn('invalid_log', 'record', 'expected_object', line=line_number); continue
                role, silent = canonical_team_role(raw.get('role'))
                if silent:
                    continue
                if sensitive(raw):
                    warn('redacted_log', 'record', 'sensitive_content', line=line_number); continue
                try:
                    raw = dict(raw, role=role)
                    row = clean_report(raw)
                    row.update(role=team_enum(raw, 'role', TEAM_ROLES), status=team_enum(raw, 'status', TEAM_STATUSES),
                               phase=team_enum(raw, 'phase', {f'P{i}' for i in range(8)}), meeting=team_text(raw, 'meeting'))
                    if 'id' in raw: row['id'] = team_text(raw, 'id')
                    logs.append(row)
                except TeamFieldError as exc:
                    warn('invalid_log', exc.field, exc.reason, line=line_number)
    except FileNotFoundError: warnings['missing_files'] += 1
    except (OSError, UnicodeError): warn('invalid_log', 'file', 'unreadable', line=0)
    unique, anonymous = {}, []
    for row in logs:
        if 'id' not in row: anonymous.append(row)
        else:
            previous = unique.get(row['id'])
            if previous: warnings['duplicate_log'] += 1
            if previous is None or row['ts'] >= previous['ts']: unique[row['id']] = row
    try:
        raw = json.loads((root / 'team_status.json').read_text(encoding='utf-8'))
        if not isinstance(raw, dict): raise TeamFieldError('record', 'expected_object')
        if not isinstance(raw.get('roles'), dict): raise TeamFieldError('roles', 'expected_object')
        metadata = {k: v for k, v in raw.items() if k != 'roles'}
        if sensitive(metadata):
            warn('redacted_status', 'metadata', 'sensitive_content', role='metadata'); raw = {'roles': {}}
        elif any(raw.get(k) is not None for k in ('updated_at', 'meeting', 'phase')):
            phase = team_enum(raw, 'phase', {f'P{i}' for i in range(8)})
            status.update(updated_at=team_ts(raw.get('updated_at'), 'updated_at'), meeting=team_text(raw, 'meeting'), phase=phase)
        pending = []
        for role, record in raw['roles'].items():
            canonical, silent = canonical_team_role(role)
            if silent:
                continue
            pending.append((role, canonical, record))
        # Prefer an explicit current-role key over a legacy alias that maps to it.
        pending.sort(key=lambda item: 0 if item[0] in TEAM_ROLES else 1)
        seen = set()
        for original, role, record in pending:
            if role in seen:
                continue
            location = role if role in TEAM_ROLES else (original if original in TEAM_ROLES else 'unknown')
            if sensitive(original) or sensitive(role) or sensitive(record):
                warn('redacted_status', 'record', 'sensitive_content', role=location); continue
            try:
                if role not in TEAM_ROLES: raise TeamFieldError('role', 'invalid_enum')
                if not isinstance(record, dict): raise TeamFieldError('record', 'expected_object')
                status['roles'][role] = dict(name=TEAM_ROLES[role], status=team_enum(record, 'status', TEAM_STATUSES),
                    task=team_text(record, 'task', 200, empty=True),
                    last_report=clean_report(record['last_report']) if record.get('last_report') is not None else None)
                seen.add(role)
            except TeamFieldError as exc:
                warn('invalid_status', exc.field, exc.reason, role=location)
    except FileNotFoundError: warnings['missing_files'] += 1
    except TeamFieldError as exc: warn('invalid_status', exc.field, exc.reason, role='metadata')
    except (OSError, UnicodeError, ValueError): warn('invalid_status', 'json', 'unreadable_or_malformed', role='metadata')
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


def pause_metadata(root):
    """Read only the public pause allowlist; never follow local archive pointers."""
    path = Path(root) / 'paper_main' / 'PAUSED.json'
    if not path.exists(): return None
    raw = json.loads(path.read_text(encoding='utf-8'))
    if raw.get('paused') is not True: return None
    reset_at = iso(raw.get('reset_at')) if raw.get('reset') is True else None
    if raw.get('reset') is True and not reset_at: raise ValueError('重置时间无效')
    return dict(paused=True, reset=raw.get('reset') is True, reset_at=reset_at,
                since=max(filter(None, [iso(raw.get('since')), reset_at]), default=None),
                message='模拟盘已暂停，等待重新开始' if reset_at else '模拟盘已暂停',
                next_initial_equity=numeric(raw.get('next_initial_equity'), 100),
                final_equity=numeric(raw.get('final_equity')))


def reset_cutoff(root):
    return (pause_metadata(root) or {}).get('reset_at')


def after_reset(stamp, cutoff):
    return not cutoff or bool(iso(stamp) and iso(stamp) >= cutoff)


def filter_team_reset(team, cutoff):
    if not cutoff: return team
    team['log'] = [r for r in team['log'] if after_reset(r['ts'], cutoff)]
    status = team['status']
    if not after_reset(status['updated_at'], cutoff):
        team['status'] = dict(updated_at=None, meeting=None, phase=None, roles={})
    else:
        for role in status['roles'].values():
            if role['last_report'] and not after_reset(role['last_report']['ts'], cutoff): role['last_report'] = None
    return team


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def downsample(points, limit=500):
    """等距取样，保留首尾，时间顺序不变。"""
    if len(points) <= limit:
        return points
    return [points[round(i * (len(points) - 1) / (limit - 1))] for i in range(limit)]


def quantity_fields(data, spec=None):
    """Runner quantity is base currency; only explicit contract counts use ctVal."""
    spec = spec if isinstance(spec, dict) else {}
    ct_val = numeric(data.get('ctVal', spec.get('ctVal')))
    ct_mult = numeric(data.get('ctMult', spec.get('ctMult')), 1)
    qty = numeric(data.get('qty', data.get('quantity')))
    contracts = numeric(data.get('contracts'))
    if data.get('qty_unit') == 'contracts':
        contracts, qty = qty, None
    if qty is None and contracts is not None and ct_val is not None and ct_val > 0 and ct_mult > 0:
        qty = contracts * ct_val * ct_mult
    return dict(qty=qty if qty is not None and qty > 0 else None, qty_unit='base',
                ctVal=ct_val if ct_val is not None and ct_val > 0 else None,
                ctMult=ct_mult if ct_mult > 0 else None)


def clean_position(symbol, data, spec=None):
    if not SYMBOL.fullmatch(symbol) or not isinstance(data, dict):
        raise ValueError('无效持仓')
    result = {'symbol': symbol}
    for key in ('side', 'qty', 'entry', 'stop', 'margin', 'liquidation_price', 'leverage', 'take_profit', 'mark_price', 'unrealized_pnl'):
        result[key] = numeric(data.get(key, data.get({'qty': 'quantity', 'liquidation_price': 'liq', 'take_profit': 'target'}.get(key, key))))
    result.update(quantity_fields(data, spec))
    result['planned_risk'] = numeric(data.get('planned_risk'))
    result['notional'] = numeric(data.get('notional'))
    if result['notional'] is not None and result['notional'] <= 0:
        result['notional'] = None
    if result['side'] not in (-1, 1) or any(result[k] is None or result[k] <= 0 for k in ('qty', 'entry', 'stop')):
        raise ValueError('持仓数值不完整')
    result['side'] = int(result['side'])
    if result['margin'] is None or result['margin'] < 0:
        raise ValueError('持仓保证金不完整')
    result['entry_time'] = iso(data.get('entry_time'))
    result['strategy'] = data.get('strategy') if data.get('strategy') in ('ema', 'breakout', 'mean_reversion', 'manual') else None
    return result


def clean_manual_status(raw, specs=None):
    """会议手工单只公开展示字段，不复制订单 ID、备注或运行器原因。"""
    rows = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get('status') not in ('pending', 'filled', 'expired', 'rejected', 'cancelled'):
            continue
        order = row.get('order') if isinstance(row.get('order'), dict) else row
        symbol = order.get('symbol', order.get('instId', row.get('symbol')))
        side = order.get('side')
        item = dict(symbol=symbol if isinstance(symbol, str) and SYMBOL.fullmatch(symbol) else None,
                    side=1 if side in (1, 'long') else -1 if side in (-1, 'short') else None,
                    status=row['status'], valid_until=iso(order.get('valid_until')))
        for key, alias in (('limit', 'entry'), ('stop', 'stop'), ('take_profit', 'target')):
            value = numeric(order.get(key, order.get('limit_price' if key == 'limit' else alias, order.get(alias))))
            item[key] = value if value is not None and value > 0 else None
        values = dict(order, **{k: row[k] for k in ('qty', 'quantity', 'contracts', 'qty_unit', 'ctVal', 'ctMult', 'notional', 'planned_risk', 'margin', 'leverage') if k in row})
        item.update(quantity_fields(values, (specs or {}).get(symbol)))
        for key in ('planned_risk', 'margin', 'leverage', 'notional'):
            v = numeric(values.get(key))
            item[key] = v if v is not None and v >= 0 else None
        if item['notional'] is None:
            size = numeric(values.get('size_usdt'))
            item['notional'] = size if size is not None and size > 0 else None
        if item['qty'] is None and item['notional'] is not None and item['limit']:
            item['qty'] = item['notional'] / item['limit']
        if item['notional'] is None and item['qty'] and item['limit']:
            item['notional'] = item['qty'] * item['limit']
        if item['planned_risk'] is None and item['qty'] and item['limit'] and item['stop']:
            item['planned_risk'] = abs(item['limit'] - item['stop']) * item['qty']
        result.append(item)
    return result


def clean_pending_orders(raw, specs=None):
    rows = raw.items() if isinstance(raw, dict) else enumerate(raw) if isinstance(raw, list) else []
    result = []
    for key, row in rows:
        if not isinstance(row, dict) or row.get('status', 'pending') != 'pending':
            continue
        symbol = row.get('symbol', row.get('instId', key))
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            continue
        stamp = iso(row.get('valid_until'))
        if stamp is None and numeric(row.get('expires_ts')) is not None:
            try:
                stamp = datetime.fromtimestamp(float(row['expires_ts'])/1000, timezone.utc).isoformat().replace('+00:00', 'Z')
            except (ValueError, OverflowError, OSError):
                pass
        cleaned = clean_manual_status([dict(row, symbol=symbol, status='pending', valid_until=stamp)], specs)
        if cleaned:
            cleaned[0]['strategy'] = row.get('strategy') if row.get('strategy') in ('ema', 'breakout', 'mean_reversion', 'manual') else None
            result.extend(cleaned)
    return result


def manual_status(directory, state):
    rows = clean_manual_status(state.get('manual_status'), state.get('market_specs'))
    if rows:
        return rows
    try:
        scan = json.loads((directory / 'scan.json').read_text(encoding='utf-8'))
        return clean_manual_status(scan.get('manual_status')) if isinstance(scan, dict) else []
    except (OSError, ValueError, UnicodeError):
        return []


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
    pause = pause_metadata(root) if account_id == 'paper_main' else None
    cutoff = (pause or {}).get('reset_at')
    if pause and not state_path.exists():
        if not pause['reset']: raise ValueError('暂停账户缺少状态')
        initial = pause['next_initial_equity']
        if initial <= 0: raise ValueError('初始权益无效')
        return dict(id=account_id, name=name, status='暂停', balance=initial, marked_equity=initial,
                    positions=[], trades=[], equity=[], risk=None,
                    updated_at=cutoff, initial=initial, day=None, day_start=None, manual_status=[], pending_orders=[], pause=pause)
    raw = state_path.read_bytes()
    state = json.loads(raw)
    balance = numeric(state.get('balance'))
    if balance is None or not isinstance(state.get('engines'), dict):
        raise ValueError('模拟盘状态不完整')
    positions = [clean_position(symbol, engine['position'], state.get('market_specs', {}).get(symbol)) for symbol, engine in state['engines'].items() if engine.get('position') and after_reset(engine['position'].get('entry_time'), cutoff)]
    marked_equity = balance
    for position in positions:
        mark = numeric(state.get('prices', {}).get(position['symbol']))
        if mark is None or mark <= 0:
            raise ValueError('持仓标记价格缺失')
        marked_equity += max(-position['margin'], position['side'] * position['qty'] * (mark - position['entry']))
        if position.get('notional') is None:
            position['notional'] = position['qty'] * mark
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
    closed = read_csv(directory / 'trades.csv') if (directory / 'trades.csv').exists() else []
    closed += [dict(t, symbol=s) for s, engine in state['engines'].items() for t in engine.get('trades', [])]
    for row in closed:
        trade = clean_trade(row)
        if trade:
            trades[(trade['symbol'], trade['kind'], trade['timestamp'], trade['entry_time'])] = trade
    updated = None
    lifecycle = None
    # events 只提取开仓成交和 poll 时间；不公开日志文本、异常或任意嵌套字段。
    from contextlib import nullcontext
    with ((directory / 'events.jsonl').open(encoding='utf-8') if (directory / 'events.jsonl').exists() else nullcontext([])) as handle:
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
    for row in (read_csv(directory / 'equity.csv') if (directory / 'equity.csv').exists() else []):
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
    return dict(id=account_id, name=name, status='暂停' if pause else '已停止' if stopped else '运行中', balance=balance, marked_equity=marked_equity,
                positions=positions, trades=sorted((t for t in trades.values() if after_reset(t['timestamp'], cutoff) and after_reset(t['entry_time'], cutoff)), key=lambda t: t['timestamp'], reverse=True),
                equity=downsample([curve[t] for t in sorted(curve) if after_reset(t, cutoff)]), risk=risk,
                **(dict(pause=dict(pause, final_equity=marked_equity)) if pause else {}),
                updated_at=max(filter(None, [updated, cutoff]), default=None), initial=numeric(state.get('initial')),
                day=state.get('day') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(state.get('day', ''))) else None,
                day_start=numeric(state.get('day_start')),
                **(dict(manual_status=manual_status(directory, state), pending_orders=clean_pending_orders(state.get('pending_orders'), state.get('market_specs'))) if account_id == 'paper_main' else {}))


def build_snapshot(source_root, now=None):
    generated = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    root = Path(source_root)
    names = dict(ACCOUNTS, paper_main='主力盘')
    directories = sorted(p for p in root.glob('paper_*') if p.is_dir() and p.name in names)
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
    if not after_reset(raw.get('updated_at'), reset_cutoff(root)):
        return dict(status='missing', updated_at=None, meeting=None, version=None, symbols={}, blackout_windows=[], global_size_factor=None)
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
    for account_id, name in [('paper_main', '主力策略')]:
        directory = root / account_id
        if not directory.exists():
            accounts.append(dict(id=account_id, name=name, mode='paper', status='未启动', equity=None,
                balance=None, daily_pnl=None, daily_loss_limit=None, positions=[], fills=[], equity_curve=[],
                updated_at=None, initial=None, day=None, day_start=None, risk=None, strategies={}, strategy_enabled=None))
            continue
        account = next((a for a in (legacy or {}).get('accounts', []) if a['id'] == account_id), None)
        account = account or build_account(root, account_id, name, now)
        state_path = directory / 'state.json'
        raw = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
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
            if strategy == 'mean_reversion' and strategy in raw.get('enabled_strategies', raw.get('strategies', {})) and isinstance(parameters, dict):
                strategies[strategy] = {k: numeric(v) for k, v in parameters.items()
                                        if k in ('fast', 'slow', 'lookback', 'volume', 'rsi', 'trend') and numeric(v) is not None}
        accounts.append(dict(id=account_id, name=name, mode='paper', status=status, equity=account['marked_equity'],
            balance=account['balance'], daily_pnl=(account['marked_equity'] - account['day_start'])
            if account['day'] == day and account['day_start'] is not None else None,
            daily_loss_limit=account['risk']['daily_loss_limit'] if account['risk'] else None, positions=account['positions'], fills=fills,
            equity_curve=account['equity'], updated_at=iso(raw.get('updated_at')) or account['updated_at'], initial=account['initial'],
            day=account['day'], day_start=account['day_start'], risk=account['risk'], strategies=strategies,
            enabled_strategies=[s for s in raw.get('enabled_strategies',strategies) if s in strategies],
            entry_mode_by_strategy={s:raw.get('entry_mode_by_strategy',{}).get(s,raw.get('entry_mode','taker'))
                for s in strategies if raw.get('entry_mode_by_strategy',{}).get(s,raw.get('entry_mode','taker')) in ('maker','taker')},
            strategy_enabled=status not in ('已停止', '暂停'), manual_status=account.get('manual_status', []), pending_orders=account.get('pending_orders', [])))
    return dict(mode='paper', source='本地模拟盘公开快照', updated_at=now.isoformat().replace('+00:00', 'Z'),
                accounts=accounts, decisions=decisions, **(dict(pause=pause_metadata(root)) if pause_metadata(root) else {}))


def build_scan(root, now=None):
    """Only publish scan fields; never execute the runner or write its directory."""
    path=Path(root)/'paper_main'/'scan.json'
    empty=dict(schema_version=1,generated_at=None,source_status='missing',instruments=[],recent_signals=[],positions=[])
    if not path.exists(): return empty
    raw=json.loads(path.read_text(encoding='utf-8'))
    if not after_reset(raw.get('generated_at'), reset_cutoff(root)): return empty
    if not isinstance(raw,dict) or raw.get('schema_version')!=1 or not iso(raw.get('generated_at')):
        raise ValueError('扫描快照格式无效')
    state_path=Path(root)/'paper_main'/'state.json'
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    rows=[]
    strategies=tuple(s for s in ('mean_reversion','manual') if s=='manual' or s in state.get('enabled_strategies', state.get('strategies', raw.get('enabled_strategies', ['mean_reversion']))))
    def symbol(value): return isinstance(value,str) and bool(SYMBOL.fullmatch(value))
    for row in raw.get('instruments',[]):
        if not isinstance(row,dict) or not symbol(row.get('instId')): continue
        rows.append(dict(instId=row['instId'],quote_24h=numeric(row.get('quote_24h')),spread=numeric(row.get('spread')),
            leverage_cap=numeric(row.get('leverage_cap')),bar_ts=numeric(row.get('bar_ts')),
            signals={s:row.get('signals',{}).get(s) if row.get('signals',{}).get(s) in (-1,1) else None for s in strategies},
            signal_status=row.get('signal_status') if row.get('signal_status') in ('ok','insufficient_candles','unavailable') else 'unavailable',
            held=row.get('held') is True))
    recent=[]
    cutoff=(now or datetime.now(timezone.utc)).timestamp()-48*3600
    for row in raw.get('recent_signals',[]):
        stamp=iso(row.get('timestamp'))
        if (not symbol(row.get('instId')) or row.get('strategy') not in strategies or row.get('side') not in (-1,1)
                or not after_reset(stamp, reset_cutoff(root)) or not stamp or not cutoff<=datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()<=cutoff+48*3600): continue
        reason=row.get('reason')
        # Failure codes only; arbitrary source text is never published.
        reason=reason if isinstance(reason,str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}',reason) else None
        recent.append(dict(timestamp=stamp,instId=row['instId'],strategy=row['strategy'],side=row['side'],
                           opened=row.get('opened') is True,reason=reason))
    positions=[dict(instId=r['instId'],strategy=r.get('strategy') if r.get('strategy') in (*strategies, 'manual') else None,
                    side=r.get('side') if r.get('side') in (-1,1) else None,entry_time=iso(r.get('entry_time')))
               for r in raw.get('positions',[]) if isinstance(r,dict) and symbol(r.get('instId')) and after_reset(r.get('entry_time'), reset_cutoff(root))]
    return dict(schema_version=1,generated_at=iso(raw['generated_at']),source_status='ok',instruments=rows,
                recent_signals=sorted(recent,key=lambda r:r['timestamp'],reverse=True),positions=positions,
                manual_status=manual_status(path.parent, state),
                pending_orders=clean_pending_orders(state.get('pending_orders', raw.get('pending_orders')), state.get('market_specs')))


# Runner events use fixed vocabularies. Alerts have a separate publication filter.
EVENT_TYPES = {'universe_refreshed', 'signal', 'stale_signal_skip', 'risk_skip', 'decision_skip',
    'trade_opened', 'trade_closed', 'daily_halt', 'config_changed', 'started', 'stopped', 'resumed',
    'interrupted', 'maker_placed', 'maker_cancelled', 'funding_observed', 'funding', 'network_error',
    'decision_close', 'skipped_min_size', 'skipped_cap', 'liquidated'}
EVENT_REASONS = dict(stop='止损', stop_live='止损', stop_loss='止损', take_profit='止盈',
    liquidated='逐仓强平', liquidation='逐仓强平', daily_halted='日亏触线停手', daily_halt='日亏触线停手',
    blackout='事件窗口禁开新仓', invalid_decisions='决议无效', bias_long='决议仅允许多头',
    bias_short='决议仅允许空头', bias_watch='会议决议观察', bias_ban='会议决议禁开仓', ban='会议决议禁开仓',
    size_factor_zero='仓位系数为零', strategy_disabled='策略未启用', already_held='已有持仓',
    pending_order='已有挂单', maker_pending='挂单待成交', expired='挂单到期未成交',
    stale_signal='信号超过入场期限', missing_price='缺少现价', initialize_only='仅初始化',
    entry_mode_changed='入场方式已更改', risk_or_margin_or_minimum='风险 / 保证金 / 最小数量限制',
    same_direction_risk='同向风险上限', stop_distance='止损距离限制', risk_or_universe='风险或币池限制',
    end='策略结束', end_of_data='数据区间结束', signal='策略信号', unknown_instrument='合约不可用')


def clean_event(raw):
    if not isinstance(raw, dict): return None
    kind = raw.get('event', raw.get('type'))
    if not isinstance(kind, str) or kind not in EVENT_TYPES: return None
    try: stamp = team_ts(raw.get('timestamp', raw.get('ts')))
    except TeamFieldError: return None
    symbol = raw.get('symbol', raw.get('instId'))
    symbol = symbol if isinstance(symbol, str) and SYMBOL.fullmatch(symbol) and not sensitive(symbol) else None
    strategy = raw.get('strategy')
    strategy = strategy if isinstance(strategy, str) and strategy in ('ema', 'breakout', 'mean_reversion') else None
    code = raw.get('reason')
    reason = EVENT_REASONS.get(code, '原因未公开' if code is not None else None) if isinstance(code, (str, type(None))) else '原因未公开'
    if kind == 'universe_refreshed':
        count = numeric(raw.get('count'))
        reason = f'{int(count)} 个币' if count is not None and 0 <= count <= 100000 and count.is_integer() else '币池数量未提供'
    if kind == 'config_changed': reason = '策略配置已更新'
    if kind == 'network_error': reason = '公共数据暂不可用'
    if code == 'daily_halted' and kind == 'risk_skip': kind = 'daily_halt'
    side = raw.get('side')
    price = numeric(raw.get('price', raw.get('exit', raw.get('entry', raw.get('reference', raw.get('limit'))))))
    return dict(ts=stamp, type=kind, coin=symbol, strategy=strategy,
                direction='多' if side == 1 else '空' if side == -1 else None,
                price=price if price is not None and price > 0 else None, reason=reason)


def build_events(source_root, now=None):
    from collections import deque
    events, sources = [], 0
    cutoff = reset_cutoff(source_root)
    for directory in ('paper_main',):
        try:
            with (Path(source_root) / directory / 'events.jsonl').open(encoding='utf-8') as handle:
                recent = deque(handle, maxlen=300)
            sources += 1
        except (FileNotFoundError, OSError, UnicodeError): continue
        for line in recent:
            try: raw = json.loads(line)
            except ValueError: continue
            row = clean_event(raw)
            if row is not None and after_reset(row['ts'], cutoff): events.append(row)
    try:
        with (Path(source_root) / 'alerts.jsonl').open(encoding='utf-8') as handle:
            recent_alerts = deque(handle, maxlen=100)
        sources += 1
    except (OSError, UnicodeError):
        recent_alerts = []
    for line in recent_alerts:
        try: raw = json.loads(line)
        except ValueError: continue
        row = clean_alert(raw)
        if row is not None and after_reset(row['ts'], cutoff): events.append(row)
    return dict(schema_version=1, generated_at=(now or datetime.now(timezone.utc)).isoformat(),
                source_status='ok' if sources else 'missing',
                events=sorted(events, key=lambda r: r['ts'])[-300:])


def public_https_url(value):
    if not isinstance(value, str) or len(value) > 500 or sensitive(value) or re.search(r'[\s\\\x00-\x1f]', value):
        return None
    try:
        url = urlsplit(value)
        host = (url.hostname or '').lower().rstrip('.')
        if url.scheme != 'https' or url.username is not None or url.password is not None or url.port not in (None, 443):
            return None
        try:
            if not ipaddress.ip_address(host).is_global: return None
        except ValueError:
            if (not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}', host)
                    or host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid', '.example', '.home', '.lan'))):
                return None
        return value
    except ValueError:
        return None


def clean_alert(raw):
    if not isinstance(raw, dict): return None
    try: stamp = team_ts(raw.get('ts'))
    except TeamFieldError: return None
    symbol = raw.get('symbol')
    if isinstance(symbol, str) and re.fullmatch(r'[A-Z0-9]{1,20}', symbol): symbol += '-USDT-SWAP'
    symbol = symbol if isinstance(symbol, str) and SYMBOL.fullmatch(symbol) and not sensitive(symbol) else None
    labels = {'breakout':'价格突破','volume':'成交量','volume_spike':'放量','funding':'资金费率',
              'oi':'持仓量','price_change':'价格波动','oi_change':'持仓量变化','放量':'放量'}
    label = labels.get(raw.get('type'), '市场异动') if isinstance(raw.get('type'), str) else '市场异动'
    value = numeric(raw.get('value'))
    parts = [label] + ([str(value)] if value is not None else [])
    result = dict(ts=stamp, type='异动', coin=symbol, strategy=None, direction=None, price=None,
                  reason=' · '.join(parts)[:80] or '市场异动', wake=raw.get('wake') is True)
    url = public_https_url(raw.get('source_url'))
    if url: result['source_url'] = url
    return result


def write_snapshot(snapshot, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8')
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path('/workspace/crypto-bot'))
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent / 'paper/snapshot.json')
    parser.add_argument('--account-source-root', type=Path, help='可选只读账户归档根目录；决议/异动仍读取 source-root')
    parser.add_argument('--historical', action='store_true', help='只读归档：标记主力盘已停止，禁止把归档显示为运行中')
    parser.add_argument('--account-output', type=Path, help='统一账户快照，默认 account.json')
    parser.add_argument('--team-only', action='store_true', help='只更新团队公开数据')
    parser.add_argument('--team-root', type=Path, help='团队源目录，默认 source-root/team')
    parser.add_argument('--team-output', type=Path, help='默认在快照输出旁生成 team.json')
    args = parser.parse_args()
    try:
        team = filter_team_reset(build_team(args.team_root or args.source_root / 'team'), reset_cutoff(args.source_root))
        if args.team_only:
            write_snapshot(team, args.team_output or args.output.with_name('team.json'))
            print('已生成团队公开数据。')
            return
        account_root = args.source_root if reset_cutoff(args.source_root) else args.account_source_root or args.source_root
        snapshot = dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                        accounts=[build_account(account_root, 'paper_main', '主力盘')] if (account_root / 'paper_main').exists() else [])
        if snapshot is not None:
            if args.historical and not pause_metadata(args.source_root):
                for account in snapshot['accounts']:
                    account['status'] = '已停止'
            scan = build_scan(account_root)
            public = build_public_accounts(account_root, legacy=snapshot)
            public['decisions'] = build_decisions(args.source_root)
            from validate_account import validate_account
            validate_account(public)
            from history_snapshot import build_history
            history = build_history(account_root, context_root=args.source_root)
            history['historical'] = args.historical and not bool(pause_metadata(args.source_root))
            write_snapshot(history, args.output.with_name('history.json'))
            write_snapshot(snapshot, args.output)
            write_snapshot(public, args.account_output or args.output.with_name('account.json'))
            write_snapshot(public['decisions'], args.output.with_name('decisions.json'))
            write_snapshot(scan, args.output.with_name('scan.json'))
            write_snapshot(build_events(args.source_root), args.output.with_name('events.json'))
        write_snapshot(team, args.team_output or args.output.with_name('team.json'))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # 控制台也不复制可能包含任意原始内容的解析异常。
        parser.exit(1, f'快照未更新：读取或校验失败（{type(exc).__name__}），请检查主力盘源文件后重试。\n')
    print('已生成公开快照、团队与账户历史数据。')


if __name__ == '__main__':
    main()
