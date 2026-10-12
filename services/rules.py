"""Deterministic hard rules. Currency is Decimal; intervals are [min, max)."""
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from services.errors import BusinessError, require


def money(value):
    try:
        result = Decimal(str(value))
        require(result.is_finite() and 0 < result <= Decimal('999999999999.99'), '金额必须为有限正数且在上限内')
        require(result == result.quantize(Decimal('0.01')), '金额最多两位小数')
        return result.quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError):
        raise BusinessError('无效金额') from None


def outcome(passed, code, reason):
    return dict(passed=bool(passed), rule_code=code, reason=reason)


def budget_check(available, amount):
    amount = money(amount)
    return outcome(available >= amount, 'BUDGET', f'可用预算 {available}，申请金额 {amount}')


def supplier_status_check(status):
    return outcome(status == 'ACTIVE', 'SUPPLIER_STATUS', f'供应商状态 {status}')


def supplier_qualification_check(qualifications, today=None, required=('BUSINESS_LICENSE','QUALITY_CERT')):
    today = today or date.today()
    valid = {q['qualification_type'] for q in qualifications
             if q['status'] == 'ACTIVE' and q['valid_from'] <= today <= q['valid_until']}
    missing = sorted(set(required) - valid)
    return outcome(not missing, 'SUPPLIER_QUALIFICATION', '缺少有效关键资质: ' + ','.join(missing) if missing else '关键资质有效')


def quantity_check(quantity, available):
    return outcome(type(quantity) is int and 0 < quantity <= available, 'QUANTITY', f'需求 {quantity}，可用 {available}')


def budget_limit_check(amount, limit):
    return outcome(money(amount) <= money(limit), 'BUDGET_LIMIT', f'金额 {amount}，限额 {limit}')


def delivery_deadline_check(delivery_days, max_delivery_days):
    return outcome(0 < delivery_days <= max_delivery_days, 'DELIVERY_DEADLINE', f'预计交期{delivery_days}天，要求{max_delivery_days}天')


def quote_validity_check(quote, today=None):
    today = today or date.today()
    return outcome(quote['status'] == 'ACTIVE' and quote['valid_from'] <= today <= quote['valid_until'], 'QUOTE_VALIDITY', '报价状态和有效期检查')


def minimum_quote_count_check(amount, count, threshold=Decimal('100000'), minimum=3):
    return outcome(type(count) is int and count >= 0 and (money(amount) <= threshold or count >= minimum),
                   'MINIMUM_QUOTE_COUNT', f'金额超过{threshold}时至少需要{minimum}家有效报价，当前{count}家')


def approval_level_resolution(amount, configured=None):
    amount = money(amount)
    baseline = ([] if amount < 5000 else ['部门经理'] if amount < 50000
                else ['部门经理','采购经理'] if amount < 200000 else ['部门经理','采购经理','财务负责人'])
    if configured is None:
        return baseline
    matches = [r for r in configured if r['enabled'] and r['min_amount'] <= amount
               and (r['max_amount'] is None or amount < r['max_amount'])]
    require(len(matches) == 1, '审批规则缺失或区间重叠')
    chain = json.loads(matches[0]['approval_chain_json'])
    require(isinstance(chain, list) and all(isinstance(x, str) for x in chain), '审批链配置无效')
    require(all(role in chain for role in baseline), '审批配置不可弱化硬规则')
    return chain
