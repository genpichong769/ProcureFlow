from datetime import date, timedelta
from decimal import Decimal
import pytest
from services import rules
from services.errors import BusinessError


@pytest.mark.parametrize('amount,length',[(1,0),(4999.99,0),(5000,1),(49999.99,1),(50000,2),(199999.99,2),(200000,3)])
def test_approval_boundaries(amount,length):
    assert len(rules.approval_level_resolution(amount)) == length


@pytest.mark.parametrize('value',['NaN','Infinity','-Infinity','0','-1','1.001','abc'])
def test_invalid_money(value):
    with pytest.raises(BusinessError):
        rules.money(value)


def test_hard_rule_boundaries():
    assert rules.minimum_quote_count_check(100000,0)['passed']
    assert not rules.minimum_quote_count_check('100000.01',2)['passed']
    assert rules.minimum_quote_count_check('100000.01',3)['passed']
    assert rules.delivery_deadline_check(7,7)['passed']
    assert not rules.delivery_deadline_check(12,7)['passed']
    assert not rules.quantity_check(True,100)['passed']
    assert not rules.quantity_check(0,100)['passed']
    assert rules.quantity_check(100,100)['passed']
    assert rules.budget_check(Decimal('0.30'),Decimal('0.30'))['passed']
    assert not rules.budget_limit_check('1.01','1.00')['passed']


def test_quote_date_inclusive():
    quote = dict(status='ACTIVE',valid_from=date.today(),valid_until=date.today())
    assert rules.quote_validity_check(quote)['passed']
    quote['valid_from'] += timedelta(days=1)
    assert not rules.quote_validity_check(quote)['passed']
