"""History publication: explicit field selection, no raw messages or private IDs."""
import json
import re
from pathlib import Path
from datetime import datetime, timezone

STRATEGIES = ('mean_reversion', 'breakout', 'manual')


def build_history(root, now=None, context_root=None):
    from make_snapshot import read_csv, iso, numeric, SYMBOL, sensitive, quantity_fields, reset_cutoff, after_reset
    root = Path(root)
    directory = root / 'paper_main'
    context_root = Path(context_root) if context_root is not None else root
    now = now or datetime.now(timezone.utc)
    cutoff = reset_cutoff(context_root)
    state_path = directory / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    decision_path = context_root / 'decisions.json'
    decision = json.loads(decision_path.read_text()) if decision_path.exists() else {}

    if not after_reset(decision.get('updated_at'), cutoff): decision = {}

    def symbol(row):
        s = row.get('symbol', row.get('instId'))
        if isinstance(s, str) and re.fullmatch(r'[A-Z0-9]{1,20}', s):
            s += '-USDT-SWAP'
        return s if isinstance(s, str) and SYMBOL.fullmatch(s) and not sensitive(s) else None

    def code(value):
        # Unknown reason codes remain unchanged, never accept a raw message.
        return value if isinstance(value, str) and re.fullmatch(r'[\w.-]{1,64}', value) and not sensitive(value) else None

    def stamp(row, field):
        value = iso(row.get(field + '_time'))
        ts = numeric(row.get(field + '_ts'))
        return value or (iso(datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat()) if ts is not None and 0 <= ts < 253402300799000 else None)

    trades = []
    private_trade_rows = []
    for raw in (read_csv(directory / 'trades.csv') if (directory / 'trades.csv').exists() else []):
        s, entry_at, exit_at = symbol(raw), stamp(raw, 'entry'), stamp(raw, 'exit')
        if not after_reset(entry_at, cutoff) or not after_reset(exit_at, cutoff) or not s or not entry_at or not exit_at or raw.get('strategy') not in STRATEGIES:
            continue
        qty = quantity_fields(raw, state.get('market_specs', {}).get(s))['qty']
        entry, exit_price, side = numeric(raw.get('entry')), numeric(raw.get('exit')), numeric(raw.get('side'))
        if side not in (-1, 1) or not all(v is not None and v > 0 for v in (qty, entry, exit_price)):
            continue
        pnl = numeric(raw.get('net_pnl', raw.get('pnl')))
        margin = numeric(raw.get('margin'))
        fee = numeric(raw.get('fee', raw.get('fees')))
        gross = numeric(raw.get('gross_pnl'), side * qty * (exit_price - entry))
        item = dict(symbol=s, strategy=raw['strategy'], side=int(side), entry_time=entry_at, exit_time=exit_at,
                    qty=qty, leverage=numeric(raw.get('leverage')), entry=entry, exit=exit_price,
                    notional=qty * entry, margin=margin, pnl=pnl,
                    pnl_percent=pnl / margin * 100 if pnl is not None and margin is not None and margin > 0 else None,
                    fee=fee, gross_pnl=gross, reason=code(raw.get('reason')))
        if item not in trades:
            trades.append(item)
            private_trade_rows.append((raw, item))
    trades.sort(key=lambda t: t['exit_time'], reverse=True)
    equity = {}
    for row in (read_csv(directory / 'equity.csv') if (directory / 'equity.csv').exists() else []):
        ts, value = iso(row.get('timestamp')), numeric(row.get('equity'))
        if ts and value is not None and after_reset(ts, cutoff):
            equity[ts] = dict(timestamp=ts, equity=value)

    # Keep only wake timestamps, symbols and fixed type labels; never detail/note.
    groups = {}
    alert_paths = dict.fromkeys([root / 'alerts.jsonl', context_root / 'alerts.jsonl'])
    for path in alert_paths:
      if path.exists():
        with path.open() as handle:
            for line in handle:
                try:
                    raw = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(raw, dict) or raw.get('wake') is not True:
                    continue
                ts, s = iso(raw.get('ts')), symbol(raw)
                index = raw.get('wake_index')
                index = int(index) if type(index) in (int, float) and numeric(index) is not None and index >= 0 and int(index) == index else None
                if not ts or not s or not after_reset(ts, cutoff):
                    continue
                key = ('index', index) if index is not None else ('ts', ts)
                group = groups.setdefault(key, dict(wake_index=index, timestamp=ts, alerts=[], orders=[]))
                group['timestamp'] = min(group['timestamp'], ts)
                kind = raw.get('type')
                kind = kind if kind in ('breakout', 'price', 'volume', 'funding', 'oi', 'price_change', 'volume_spike', 'funding_extreme', 'oi_change') else 'market'
                alert = dict(ts=ts, symbol=s, type=kind)
                if alert not in group['alerts']:
                    group['alerts'].append(alert)

    statuses = state.get('manual_status', {})
    status_rows = list(statuses.items()) if isinstance(statuses, dict) else [(None, s) for s in statuses] if isinstance(statuses, list) else []
    # Include older orders retained by manual_status after decisions.json changes.
    orders = [(o, True) for o in decision.get('manual_orders', []) if isinstance(o, dict)]
    known_ids = {o.get('id') for o, _ in orders if isinstance(o.get('id'), str)}
    for order_id, status in status_rows:
        order = status.get('order') if isinstance(status, dict) else None
        if isinstance(order, dict) and order_id not in known_ids:
            orders.append((dict(order, id=order_id), False))

    def ref_matches(ref, group):
        if type(ref) in (int, float) and group['wake_index'] is not None:
            return ref == group['wake_index']
        if isinstance(ref, str) and ref.isdigit() and group['wake_index'] is not None:
            return int(ref) == group['wake_index']
        return isinstance(ref, str) and iso(ref) in {a['ts'] for a in group['alerts']}

    for order, current in orders:
        s = symbol(order)
        if not s:
            continue
        order_id = order.get('id')
        status = next((r for k, r in status_rows if k == order_id and order_id is not None), None)
        if status is None:
            # List-style status has no IDs; only an unambiguous symbol + entry match.
            matches = [r for _, r in status_rows if isinstance(r, dict) and symbol(r.get('order', r)) == s
                       and numeric(r.get('order', r).get('entry')) == numeric(order.get('entry'))]
            status = matches[0] if len(matches) == 1 else {}
        times = [iso(order.get(k)) for k in ('created_at', 'updated_at', 'timestamp', 'ts', 'time', 'entry_time')]
        times += [iso(status.get('time'))]
        if current:
            times.append(iso(decision.get('updated_at')))
        times = [datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp() for t in times if t]
        ref = order.get('alert_ref', order.get('source_alert'))
        if ref is None and current:
            ref = decision.get('alert_ref', decision.get('source_alert'))
        candidates = []
        for group in groups.values():
            alerts = [a for a in group['alerts'] if a['symbol'] == s]
            if not alerts:
                continue
            if ref is not None:
                if ref_matches(ref, group):
                    candidates.append(group)
            elif any(0 <= t - datetime.fromisoformat(a['ts'].replace('Z', '+00:00')).timestamp() <= 86400 for t in times for a in alerts):
                candidates.append(group)
        # A fallback order is assigned once, to the latest eligible wake group.
        if not candidates:
            continue
        group = max(candidates, key=lambda g: g['timestamp'])
        matched = [(raw, t) for raw, t in private_trade_rows if t['strategy'] == 'manual' and t['symbol'] == s
                   and order_id is not None and raw.get('order_id') == order_id]
        if not matched and iso(status.get('time')):
            matched = [(raw, t) for raw, t in private_trade_rows if t['strategy'] == 'manual' and t['symbol'] == s and t['entry_time'] == iso(status['time'])]
        complete = bool(matched) and all(t['pnl'] is not None for _, t in matched)
        if not after_reset(status.get('time'), cutoff): continue
        group['orders'].append(dict(symbol=s, side=1 if order.get('side') in ('long', 1) else -1 if order.get('side') in ('short', -1) else None,
            status=status.get('status') if status.get('status') in ('pending', 'filled', 'expired', 'rejected', 'cancelled') else None,
            time=iso(status.get('time')), closed_time=max((t['exit_time'] for _, t in matched), default=None),
            pnl=sum(t['pnl'] for _, t in matched) if complete else None, match='exact' if ref is not None else 'time'))
    for group in groups.values():
        group['adopted'] = bool(group['orders'])
        for alert in group['alerts']:
            alert['adopted'] = any(o['symbol'] == alert['symbol'] for o in group['orders'])
    return dict(schema_version=1, account_id='paper_main', generated_at=now.isoformat(),
                reset_at=cutoff, equity=[equity[t] for t in sorted(equity)], trades=trades,
                alert_groups=sorted(groups.values(), key=lambda g: g['timestamp'], reverse=True))
