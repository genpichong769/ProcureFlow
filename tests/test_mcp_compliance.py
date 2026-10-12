from mcp_server.mcp_compliance_server import create_server
from tests.mcp_helpers import run_tools


def test_compliance_tools(db):
    results = run_tools(create_server(db),[
        ('get_supplier_qualifications',dict(supplier_id=1)),
        ('get_procurement_rules',dict(category='IT')),
        ('evaluate_procurement_compliance',dict(department=1,supplier_id=1,category='IT',total_amount='200000',valid_quote_count=3)),
    ],['get_supplier_qualifications','get_procurement_rules','evaluate_procurement_compliance'])
    assert len(results[0]['data'])==2
    assert results[1]['data'][0]['rule_code']=='THREE_QUOTES'
    assert results[2]['data']['compliance_passed']
    assert len(results[2]['data']['approval_chain'])==3
