import json
import pytest
from db.repositories.base import execute
from services.compliance_service import ComplianceService
from services.errors import BusinessError


def test_normal_and_rules(db):
    s = ComplianceService(db)
    result = s.evaluate_procurement_compliance(1,1,'IT',1000,1)
    assert result['compliance_passed'] and result['approval_chain'] == []
    assert len(s.get_supplier_qualifications(1)) == 2
    assert s.get_procurement_rules('IT')[0]['rule_type'] == 'MINIMUM_QUOTES'


@pytest.mark.parametrize('supplier',[4,5,6,7])
def test_block_invalid_suppliers(db,supplier):
    result = ComplianceService(db).evaluate_procurement_compliance(1,supplier,'IT',1000,3)
    assert not result['compliance_passed'] and result['failed_rules']


def test_minimum_three_quotes(db):
    s = ComplianceService(db)
    assert not s.evaluate_procurement_compliance(1,1,'IT',100001,2)['compliance_passed']
    assert s.evaluate_procurement_compliance(1,1,'IT',100001,3)['compliance_passed']


@pytest.mark.parametrize('amount,length',[(4999,0),(5000,1),(50000,2),(200000,3)])
def test_database_approval_chain(db,amount,length):
    assert len(ComplianceService(db).evaluate_procurement_compliance(1,1,'IT',amount,3)['approval_chain']) == length


def test_database_rules_really_apply(db):
    with db.transaction() as conn:
        execute(conn,"UPDATE procurement_rules SET rule_config_json=%s WHERE rule_code='THREE_QUOTES'",(json.dumps({'threshold':'100','minimum':4}),))
    assert not ComplianceService(db).evaluate_procurement_compliance(1,1,'IT',1000,3)['compliance_passed']


def test_unknown_enabled_rule_fails_closed(db):
    with db.transaction() as conn:
        execute(conn,"UPDATE procurement_rules SET rule_type='UNKNOWN' WHERE rule_code='THREE_QUOTES'")
    assert not ComplianceService(db).evaluate_procurement_compliance(1,1,'IT',1000,3)['compliance_passed']


def test_weakened_approval_rejected(db):
    with db.transaction() as conn:
        execute(conn,"UPDATE approval_rules SET approval_chain_json='[]' WHERE min_amount=5000")
    with pytest.raises(BusinessError,match='弱化'):
        ComplianceService(db).evaluate_procurement_compliance(1,1,'IT',5000,3)
