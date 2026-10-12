import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from agents.coordinator import ProcurementCoordinatorAgent
from agents.requirement_validation import validate_amounts
from agents.schemas import RequirementFields


@pytest.mark.parametrize(('text', 'bad'), [
    ('麻烦给 DEP009 办一下：PRD01476 来 2 个，钱别超过 403.44，60 天内送到。', '4034400.0'),
    ('麻烦给 DEP020 办一下：PRD03612 来 2 个，钱别超过 13832.63，60 天内送到。', '1383263.0'),
    ('麻烦给 DEP012 办一下：PRD03304 来 2 个，钱别超过 524.83，60 天内送到。', '5248300.0'),
])
def test_original_phase4_failures_are_corrected_from_source(text, bad):
    fields = RequirementFields(max_total_amount=bad, max_delivery_days=60, quantity=2)
    result = validate_amounts(text, fields)
    expected = Decimal(text.split('钱别超过 ')[1].split('，')[0])
    assert not result.ambiguous
    assert result.fields.max_total_amount == expected
    assert result.fields.max_unit_price is None


@pytest.mark.parametrize(('text', 'expected'), [
    ('总预算为15000元，30天内送达', Decimal('15000')),
    ('总预算1.5万元，30天内送达', Decimal('15000')),
    ('采购金额￥12,345.67，30天到货', Decimal('12345.67')),
    ('总预算一万五千元，30天内送达', Decimal('15000')),
    ('钱别超过一万五，60天内送到', Decimal('15000')),
])
def test_supported_currency_units_and_chinese_amounts(text, expected):
    result = validate_amounts(text, RequirementFields(max_total_amount='999999'))
    assert not result.ambiguous
    assert result.fields.max_total_amount == expected


def test_unit_price_and_total_budget_remain_distinct():
    text = '采购10件，单价80元，总预算900元，30天内到货'
    fields = RequirementFields(quantity=10, max_unit_price='8000', max_total_amount='90000')
    result = validate_amounts(text, fields)
    assert not result.ambiguous
    assert result.fields.max_unit_price == Decimal('80')
    assert result.fields.max_total_amount == Decimal('900')


def test_per_item_currency_expression_is_unit_price():
    result = validate_amounts('采购10件，每件80元，30天到货', RequirementFields(max_total_amount='800'))
    assert not result.ambiguous
    assert result.fields.max_unit_price == Decimal('80')
    assert result.fields.max_total_amount is None


def test_quantity_dimensions_and_delivery_are_not_money_evidence():
    text = '采购60个，规格为120×80厘米，30天内送达'
    fields = RequirementFields(quantity=60, max_total_amount='601208030', max_delivery_days=30)
    result = validate_amounts(text, fields)
    assert result.ambiguous
    assert result.fields.max_total_amount is None
    assert result.fields.max_unit_price is None


def test_dimension_range_outside_budget_clause_does_not_make_budget_ambiguous():
    result = validate_amounts('规格120-80厘米，总预算10000元，30天送达', RequirementFields(max_total_amount='10000'))
    assert not result.ambiguous
    assert result.fields.max_total_amount == Decimal('10000')


@pytest.mark.parametrize('text', [
    '总预算一万到两万元，30天内送达',
    '预算大约一万多，30天内送达',
    '预算和交期分别是15000和60',
    '最多花10000元或者12000元',
])
def test_ambiguous_amounts_require_clarification(text):
    result = validate_amounts(text, RequirementFields(max_total_amount='10000'))
    assert result.ambiguous
    assert result.fields.max_total_amount is None
    assert result.fields.max_unit_price is None


def test_normal_exact_model_value_is_unchanged():
    fields = RequirementFields(max_total_amount='50000.00')
    result = validate_amounts('总预算50000元，15天内送达', fields)
    assert not result.ambiguous
    assert result.fields.max_total_amount == Decimal('50000.00')


def test_ambiguous_budget_never_dispatches_to_agents_or_writes():
    gateway = AsyncMock()
    gateway.extract.return_value = RequirementFields(
        department_code='DEP001', product_code='PRD00001', quantity=10,
        max_total_amount='10000', max_delivery_days=30)
    transport = AsyncMock()
    proposal = asyncio.run(ProcurementCoordinatorAgent(gateway, transport).run({
        'request_id': 'BUGFIX-SAFE-1',
        'text': 'DEP001采购PRD00001共10件，预算一万到两万元，30天内送达',
    }))
    assert proposal.status == 'NEED_MORE_INFORMATION'
    assert proposal.missing_fields == ['budget']
    assert proposal.requirement.max_total_amount is None
    transport.call.assert_not_called()
