import pytest
from db.repositories.base import execute
from services.supplier_service import SupplierService
from services.errors import BusinessError


def test_normal_search_and_detail(db):
    service = SupplierService(db)
    rows = service.search_supplier_quotes('PRD00001',5,120,10)
    assert [q['quote_id'] for q in rows] == [2,1,3]
    assert rows[0]['total_price'] == 450
    assert service.get_supplier_detail(1)['status'] == 'ACTIVE'
    assert service.get_supplier_performance(1)[0]['total_orders'] == 100


@pytest.mark.parametrize('excluded',[20,21,22,23,24,25,26,27])
def test_filters_expired_stock_suspended_blacklisted_future_slow_revoked(db,excluded):
    result = SupplierService(db).search_supplier_quotes(1,5,120,10)
    assert excluded not in [row['quote_id'] for row in result]


def test_no_quotes(db):
    assert SupplierService(db).search_supplier_quotes(3,5,1000,10) == []
    assert SupplierService(db).search_supplier_quotes(1,10000,1000,10) == []
    assert SupplierService(db).search_supplier_quotes(1,5,1,10) == []


def test_invalid_inputs_and_sql_injection(db):
    s = SupplierService(db)
    with pytest.raises(BusinessError):
        s.search_supplier_quotes("1 OR 1=1; DROP TABLE suppliers",1,100,10)
    with pytest.raises(BusinessError):
        s.search_supplier_quotes(1,-1,100,10)
    assert s.get_supplier_detail(1)['id'] == 1
