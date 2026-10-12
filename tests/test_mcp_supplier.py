from mcp_server.mcp_supplier_server import create_server
from tests.mcp_helpers import run_tools


def test_supplier_tools(db):
    results = run_tools(create_server(db),[
        ('search_supplier_quotes',dict(product=1,quantity=5,max_unit_price='120',max_delivery_days=10)),
        ('get_supplier_detail',dict(supplier_id=1)),
        ('get_supplier_performance',dict(supplier_id=1)),
    ],['search_supplier_quotes','get_supplier_detail','get_supplier_performance'])
    assert len(results[0]['data'])==3
    assert results[1]['data']['on_time_rate']=='0.98500'
    assert results[2]['data'][0]['total_orders']==100
