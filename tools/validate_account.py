#!/usr/bin/env python3
"""Dependency-free validator for the keywords used by account.schema.json.
The schema is also usable with standard JSON Schema Draft 2020-12 validators.
Never prints rejected data or private source content.
"""
import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path

SCHEMA = Path(__file__).with_name('account.schema.json')


def check(value, schema):
    types = schema.get('type', [])
    types = [types] if isinstance(types, str) else types
    def matches(t):
        return {'null': value is None, 'object': isinstance(value, dict), 'array': isinstance(value, list),
                'string': isinstance(value, str), 'boolean': isinstance(value, bool),
                'number': type(value) in (int, float) and math.isfinite(value),
                'integer': type(value) is int}.get(t, False)
    if types and not any(matches(t) for t in types):
        raise ValueError('字段类型不符')
    if 'enum' in schema and not any(value == item and (isinstance(value, bool) == isinstance(item, bool)) for item in schema['enum']):
        raise ValueError('字段枚举不符')
    if value is None:
        return
    if isinstance(value, dict):
        if not set(schema.get('required', [])) <= value.keys():
            raise ValueError('缺少必要字段')
        properties = schema.get('properties', {})
        for key, item in value.items():
            if 'propertyNames' in schema:
                check(key, schema['propertyNames'])
            if key in properties:
                check(item, properties[key])
            elif schema.get('additionalProperties') is False:
                raise ValueError('含未授权字段')
            elif isinstance(schema.get('additionalProperties'), dict):
                check(item, schema['additionalProperties'])
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            raise ValueError('列表数量不足')
        for item in value:
            check(item, schema.get('items', {}))
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', float('inf')):
            raise ValueError('文本长度不符')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            raise ValueError('文本格式不符')
        if schema.get('format') == 'date-time':
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                raise ValueError('时间缺少时区')
    if type(value) in (int, float):
        if (not math.isfinite(value) or value < schema.get('minimum', -math.inf)
                or value > schema.get('maximum', math.inf)
                or ('exclusiveMinimum' in schema and value <= schema['exclusiveMinimum'])):
            raise ValueError('数值范围不符')


def validate_account(data):
    check(data, json.loads(SCHEMA.read_text()))
    ids = [a['id'] for a in data['accounts']]
    if len(set(ids)) != len(ids):
        raise ValueError('重复账户别名')
    # Reuse the publication filter, including keys, without exposing rejected content.
    from make_snapshot import sensitive
    if sensitive(data):
        raise ValueError('快照包含敏感内容')
    for account in data['accounts']:
        if account['mode'] != data['mode'] or not account['id'].startswith(data['mode'] + '_'):
            raise ValueError('账户模式不一致')
        if account['status'] == '未启动':
            if any(account[k] is not None for k in ('equity','balance','daily_pnl','daily_loss_limit')) or any(account[k] for k in ('positions','fills','equity_curve')):
                raise ValueError('未启动账户不得包含虚构指标')
        elif any(account[k] is None for k in ('equity','balance','daily_loss_limit')):
            raise ValueError('已启动账户缺少金额或风控')
        for fill in account['fills']:
            if not math.isclose(fill['notional'], fill['qty'] * fill['price'], rel_tol=1e-8):
                raise ValueError('成交额与数量价格不一致')
    for row in data['decisions']['blackout_windows']:
        if datetime.fromisoformat(row['start'].replace('Z','+00:00')) >= datetime.fromisoformat(row['end'].replace('Z','+00:00')):
            raise ValueError('事件窗口起止无效')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', type=Path, default=Path('paper/account.json'))
    args = parser.parse_args()
    try:
        validate_account(json.loads(args.path.read_text()))
    except (ValueError, TypeError, OSError, KeyError):
        parser.exit(1, '账户快照校验失败；拒绝发布。\n')
    print('账户快照 schema 与跨字段校验通过。')


if __name__ == '__main__':
    main()
