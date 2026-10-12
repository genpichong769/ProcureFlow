from mcp_server.mcp_budget_server import create_server
from tests.mcp_helpers import run_tools


def test_budget_tools(db):
    results = run_tools(create_server(db),[
        ('get_department_budget',dict(department=1)),
        ('get_budget_transactions',dict(department=1)),
        ('check_budget',dict(department=1,amount='100.00')),
        ('get_department_budget',dict(department=999)),
    ],['get_department_budget','get_budget_transactions','check_budget'])
    assert results[0]['data']['available_budget']=='1000000.00'
    assert results[1]['data']==[]
    assert results[2]['data']['passed']
    assert not results[3]['ok']
