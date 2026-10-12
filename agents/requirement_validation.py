"""Deterministic validation for high-risk numeric fields extracted by the LLM."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from agents.schemas import RequirementFields


_ARABIC = r'(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)'
_CHINESE = r'(?:[零〇一二两三四五六七八九十百千万亿点]+)'
_NUMBER = rf'(?P<number>{_ARABIC}|{_CHINESE})'
_UNIT = r'(?P<unit>亿元|万元|千元|百元|块钱|人民币元|元|万|块)?'
_PREFIX = r'(?:人民币|RMB|CNY|[¥￥])?\s*'
_LINK = r'(?:为|是|按|控制在|限定在|封顶|上限(?:为|是)?|不超过|不能超过|别超过|最多(?:为|是|花|花费)?|约|大约|大概|差不多|[=:：])?\s*'
_TOTAL_LABEL = r'(?:总预算|预算总额|预算金额|采购预算|总金额|总额上限|采购金额|金额上限|总价|预算|钱别超过|最多花(?:费)?)'
_MEASURE = r'(?:台|件|个|套|支|箱|份|本|张|辆|吨|公斤|千克|米)'
_PER_UNIT_LABEL = rf'(?:每{_MEASURE})'
_UNIT_LABEL = rf'(?:最高单价|单价上限|预算单价|单价|每{_MEASURE}(?:价格|金额|费用))'
_REQUIRED_CURRENCY_UNIT = r'(?P<unit>亿元|万元|千元|百元|块钱|人民币元|元|万|块)'

_PATTERNS = {
    'total': (
        re.compile(rf'(?P<label>{_TOTAL_LABEL})\s*{_LINK}{_PREFIX}{_NUMBER}\s*{_UNIT}', re.IGNORECASE),
        re.compile(rf'{_PREFIX}{_NUMBER}\s*{_UNIT}\s*(?:的)?(?P<label>{_TOTAL_LABEL})', re.IGNORECASE),
    ),
    'unit': (
        re.compile(rf'(?P<label>{_UNIT_LABEL})\s*{_LINK}{_PREFIX}{_NUMBER}\s*{_UNIT}', re.IGNORECASE),
        re.compile(rf'{_PREFIX}{_NUMBER}\s*{_UNIT}\s*(?:的)?(?P<label>{_UNIT_LABEL})', re.IGNORECASE),
        re.compile(rf'(?P<label>{_PER_UNIT_LABEL})\s*{_LINK}{_PREFIX}{_NUMBER}\s*{_REQUIRED_CURRENCY_UNIT}', re.IGNORECASE),
    ),
}

_MONEY_INTENT = re.compile(
    rf'{_TOTAL_LABEL}|{_UNIT_LABEL}|{_PER_UNIT_LABEL}\s*{_LINK}{_PREFIX}(?:{_ARABIC}|{_CHINESE})\s*'
    rf'(?:亿元|万元|千元|百元|块钱|人民币元|元|万|块)|[¥￥]|\b(?:RMB|CNY)\b', re.IGNORECASE)
_FUZZY = re.compile(r'(?:大约|大概|差不多|左右|上下|浮动|看情况|[零〇一二两三四五六七八九十百千万亿\d]多)')
_RANGE = re.compile(
    rf'(?:{_ARABIC}|{_CHINESE})\s*(?:亿元|万元|千元|百元|块钱|人民币元|元|万|块)?\s*'
    rf'(?:到|至|或|或者|[-~～—–])\s*(?:{_ARABIC}|{_CHINESE})')
_CHINESE_DIGITS = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
                   '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
_SMALL_UNITS = {'十': 10, '百': 100, '千': 1000}
_LARGE_UNITS = {'万': 10000, '亿': 100000000}
_SUFFIX_MULTIPLIERS = {'': Decimal(1), '元': Decimal(1), '人民币元': Decimal(1), '块': Decimal(1),
                       '块钱': Decimal(1), '百元': Decimal(100), '千元': Decimal(1000),
                       '万': Decimal(10000), '万元': Decimal(10000), '亿元': Decimal(100000000)}


@dataclass(frozen=True)
class AmountValidation:
    fields: RequirementFields
    ambiguous: bool
    evidence: dict[str, Decimal]


def _chinese_integer(value: str) -> int:
    if not value:
        raise ValueError('empty Chinese number')
    if all(char in _CHINESE_DIGITS for char in value):
        return int(''.join(str(_CHINESE_DIGITS[char]) for char in value))

    # Common spoken shorthand: 一万五 means 15,000; 三千二 means 3,200.
    shorthand = re.fullmatch(r'([一二两三四五六七八九])(万|千|百)([一二两三四五六七八九])', value)
    if shorthand:
        base = _CHINESE_DIGITS[shorthand.group(1)] * {'万': 10000, '千': 1000, '百': 100}[shorthand.group(2)]
        tail = _CHINESE_DIGITS[shorthand.group(3)] * {'万': 1000, '千': 100, '百': 10}[shorthand.group(2)]
        return base + tail

    total = section = digit = 0
    for char in value:
        if char in _CHINESE_DIGITS:
            digit = _CHINESE_DIGITS[char]
        elif char in _SMALL_UNITS:
            section += (digit or 1) * _SMALL_UNITS[char]
            digit = 0
        elif char in _LARGE_UNITS:
            section += digit
            if char == '万':
                total += section * _LARGE_UNITS[char]
            else:
                total = (total + section) * _LARGE_UNITS[char]
            section = digit = 0
        else:
            raise ValueError('invalid Chinese number')
    return total + section + digit


def _number(value: str) -> Decimal:
    value = value.replace(',', '')
    if re.fullmatch(_ARABIC, value):
        return Decimal(value)
    if '点' in value:
        whole, fraction = value.split('点', 1)
        if not fraction or any(char not in _CHINESE_DIGITS for char in fraction):
            raise ValueError('invalid Chinese decimal')
        return Decimal(_chinese_integer(whole)) + Decimal(
            '0.' + ''.join(str(_CHINESE_DIGITS[char]) for char in fraction))
    return Decimal(_chinese_integer(value))


def _amount(match: re.Match) -> Decimal:
    amount = _number(match.group('number')) * _SUFFIX_MULTIPLIERS[match.group('unit') or '']
    if amount <= 0 or amount.as_tuple().exponent < -2 or amount >= Decimal('1000000000000'):
        raise ValueError('amount outside supported currency precision or range')
    return amount.quantize(Decimal('.01'))


def validate_amounts(text: str, fields: RequirementFields) -> AmountValidation:
    """Align model amounts to explicit source evidence, or force clarification.

    Quantity, dimensions and delivery numbers are ignored because an amount is only
    accepted next to a strong total-budget or unit-price label. Any fuzzy/range
    expression is intentionally treated as ambiguous.
    """
    candidates: dict[str, list[Decimal]] = {'total': [], 'unit': []}
    parse_failed = False
    for scope, patterns in _PATTERNS.items():
        seen_spans = set()
        for pattern in patterns:
            for match in pattern.finditer(text):
                if match.span() in seen_spans:
                    continue
                seen_spans.add(match.span())
                try:
                    candidates[scope].append(_amount(match))
                except (InvalidOperation, KeyError, ValueError):
                    parse_failed = True

    unique = {scope: set(values) for scope, values in candidates.items()}
    has_intent = bool(_MONEY_INTENT.search(text) or fields.max_total_amount is not None or fields.max_unit_price is not None)
    money_clauses = []
    for intent in _MONEY_INTENT.finditer(text):
        previous = max(text.rfind(mark, 0, intent.start()) for mark in '，,。；;！!？?\n')
        following = [text.find(mark, intent.end()) for mark in '，,。；;！!？?\n']
        following = [position for position in following if position >= 0]
        money_clauses.append(text[previous + 1:min(following) if following else len(text)])
    ambiguous = has_intent and (
        parse_failed or any(_FUZZY.search(clause) or _RANGE.search(clause) for clause in money_clauses)
        or any(len(values) > 1 for values in unique.values())
        or not any(unique.values())
    )

    update = {'max_total_amount': None, 'max_unit_price': None}
    evidence: dict[str, Decimal] = {}
    if not ambiguous:
        if unique['total']:
            evidence['max_total_amount'] = next(iter(unique['total']))
            update['max_total_amount'] = evidence['max_total_amount']
        if unique['unit']:
            evidence['max_unit_price'] = next(iter(unique['unit']))
            update['max_unit_price'] = evidence['max_unit_price']
    return AmountValidation(fields=fields.model_copy(update=update), ambiguous=ambiguous, evidence=evidence)
