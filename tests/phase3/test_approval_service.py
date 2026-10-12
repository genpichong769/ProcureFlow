from datetime import date,timedelta
from decimal import Decimal
from services.procurement_service import ProcurementService


def test_real_mysql_approval_identity_record_and_rejection(db):
    service=ProcurementService(db)
    request=service.create_purchase_request(1,1,date.today()+timedelta(days=10),'phase3 service test',
        [dict(product_id=1,quantity=1,max_unit_price='120')],request_no='P3TEST-SERVICE')
    assert service.budget.reserve(request['id'])['status']=='PENDING_APPROVAL'
    assert service.validate_requester(1,'DEP001')['department_id']==1
    assert service.validate_approver(request['id'],1,'EMPLOYEE')['id']==1
    first=service.record_approval(request['id'],1,'EMPLOYEE',1,'REJECT','test')
    again=service.record_approval(request['id'],1,'EMPLOYEE',1,'REJECT','ignored idempotent comment')
    assert first['id']==again['id'] and first['decision']=='REJECTED'
    released=service.release_request_budget(request['id']);assert released['released_amount']==Decimal('120.00')
    assert service.set_purchase_request_approval(request['id'],'REJECTED')['status']=='REJECTED'
