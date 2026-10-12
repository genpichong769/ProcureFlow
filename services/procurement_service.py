from datetime import date
from decimal import Decimal
from uuid import uuid4
import re
from db.connection import database
from db.repositories.procurement_repository import ProcurementRepository
from db.repositories.supplier_repository import SupplierRepository
from db.repositories.budget_repository import BudgetRepository
from services.budget_service import BudgetService
from services.compliance_service import ComplianceService
from services.models import RequestInput, OrderItem
from services.errors import require
from services import rules


class ProcurementService:
    def __init__(self, db=database):
        self.db, self.repo, self.suppliers = db, ProcurementRepository(), SupplierRepository()
        self.budget, self.compliance = BudgetService(db), ComplianceService(db)

    def create_purchase_request(self, requester_id, department_id, required_delivery_date, reason, items, request_no=None):
        data = RequestInput(requester_id=requester_id,department_id=department_id,
            required_delivery_date=required_delivery_date,reason=reason,items=items)
        require(data.required_delivery_date >= date.today(), '要求交货日期不可早于今天')
        require(len({x.product_id for x in data.items}) == len(data.items), '产品不可重复')
        amount = rules.money(sum((i.quantity*i.max_unit_price for i in data.items),Decimal('0')))
        number = request_no or 'PR-'+uuid4().hex
        require(isinstance(number,str) and len(number)<=64 and re.fullmatch(r'(?:PR|P3|P3TEST)-[A-Za-z0-9_-]+',number), '申请编号格式无效')
        with self.db.transaction() as conn:
            existing = self.repo.request_by_no(conn,number,lock=True)
            if existing:
                current = self._request(conn,existing['id'])
                expected_items = sorted((i.product_id,i.quantity,i.max_unit_price) for i in data.items)
                actual_items = sorted((i['product_id'],i['quantity'],i['max_unit_price']) for i in current['items'])
                require(current['requester_id']==data.requester_id and current['department_id']==data.department_id
                    and current['required_delivery_date']==data.required_delivery_date and current['reason']==data.reason
                    and current['expected_budget']==amount and actual_items==expected_items,
                    '申请编号已存在但业务内容不一致')
                return current
            employee = self.repo.employee(conn,data.requester_id)
            require(employee is not None and employee['department_id'] == data.department_id and employee['status'] == 'ACTIVE', '申请人无效或不属于该部门')
            dept = BudgetRepository().department(conn,data.department_id)
            require(dept is not None and dept['status'] == 'ACTIVE', '部门不可用')
            require(BudgetRepository().get(conn,data.department_id,date.today().year) is not None, '年度预算不存在')
            for item in data.items:
                require(self.suppliers.product(conn,item.product_id) is not None, '有效产品不存在')
            request_id = self.repo.insert_request(conn,number,data,date.today().year,amount)
            for item in data.items:
                self.repo.insert_request_item(conn,request_id,item)
            return self._request(conn,request_id)

    def validate_requester(self, requester_id, department):
        with self.db.transaction() as conn:
            employee = self.repo.employee(conn,requester_id)
            dept = BudgetRepository().department(conn,department)
            require(employee is not None and employee['status']=='ACTIVE', '申请人不存在或未启用')
            require(dept is not None and dept['status']=='ACTIVE', '部门不存在或未启用')
            require(employee['department_id']==dept['id'], '申请人不属于采购部门')
            return dict(id=employee['id'],employee_no=employee['employee_no'],role=employee['role'],
                        department_id=dept['id'],department_code=dept['department_code'])

    def validate_approver(self, request_id, approver_id, required_role):
        with self.db.transaction() as conn:
            request = self.repo.request(conn,request_id)
            employee = self.repo.employee(conn,approver_id)
            require(request is not None, '申请不存在')
            require(employee is not None and employee['status']=='ACTIVE', '审批人不存在或未启用')
            require(employee['role']==required_role, '审批人角色与当前审批层级不匹配')
            require(employee['department_id']==request['department_id'], '审批人不属于采购部门')
            return dict(id=employee['id'],employee_no=employee['employee_no'],role=employee['role'],status=employee['status'])

    def record_approval(self, request_id, approver_id, required_role, approval_level, decision, comment=''):
        require(decision in ('APPROVE','REJECT'), '审批决定只能为APPROVE或REJECT')
        require(type(approval_level) is int and approval_level>0, '审批层级无效')
        require(isinstance(comment,str) and len(comment)<=1000, '审批意见过长')
        stored = 'APPROVED' if decision=='APPROVE' else 'REJECTED'
        with self.db.transaction() as conn:
            request = self.repo.request(conn,request_id,lock=True)
            employee = self.repo.employee(conn,approver_id)
            require(request is not None and request['status']=='PENDING_APPROVAL', '申请当前不在审批中')
            require(employee is not None and employee['status']=='ACTIVE', '审批人不存在或未启用')
            require(employee['role']==required_role and employee['department_id']==request['department_id'], '审批身份与当前层级不匹配')
            existing = self.repo.approval(conn,request_id,approval_level,lock=True)
            if existing:
                require(existing['approver_id']==approver_id and existing['decision']==stored,
                        '该审批层级已有不同决定')
                return existing
            approval_id = self.repo.insert_approval(conn,request_id,approver_id,approval_level,stored,comment)
            return self.repo.approval(conn,request_id,approval_level)

    def release_request_budget(self, request_id):
        with self.db.transaction() as conn:
            request = self.repo.request(conn,request_id,lock=True)
            require(request is not None and request['status'] in ('PENDING_APPROVAL','REJECTED'), '申请状态不可释放预算')
            held = self.budget.repo.reserved_for_request(conn,request_id)
            if held:
                self.budget.apply(conn,request,'RELEASE',held)
            result = self._request(conn,request_id)
            result['released_amount'] = held
            return result

    def set_purchase_request_approval(self, request_id, status):
        require(status in ('APPROVED','REJECTED'), '采购申请审批状态无效')
        with self.db.transaction() as conn:
            request = self.repo.request(conn,request_id,lock=True)
            require(request is not None, '申请不存在')
            if request['status']==status:
                return self._request(conn,request_id)
            require(request['status']=='PENDING_APPROVAL', '采购申请不在待审批状态')
            if status=='REJECTED':
                require(self.budget.repo.reserved_for_request(conn,request_id)==0, '拒绝前必须释放全部预算预占')
            self.repo.request_status(conn,request_id,status)
            return self._request(conn,request_id)

    def _request(self, conn, request_id):
        row = self.repo.request(conn,request_id)
        require(row is not None, '申请不存在')
        row['items'] = self.repo.request_items(conn,request_id)
        return row

    def get_purchase_request(self, request_id):
        with self.db.transaction() as conn:
            return self._request(conn,request_id)

    def _order(self, conn, order_id):
        row = self.repo.order(conn,order_id)
        require(row is not None, '订单不存在')
        row['items'] = self.repo.order_items(conn,order_id)
        return row

    def get_purchase_order(self, purchase_order_id):
        with self.db.transaction() as conn:
            return self._order(conn,purchase_order_id)

    def create_purchase_order(self, request_id, supplier_id=None, items=None):
        with self.db.transaction() as conn:
            # Serialize retries using the parent row, including before the first PO exists.
            request = self.repo.request(conn,request_id,lock=True)
            require(request is not None, '申请不存在')
            existing = self.repo.order_by_request(conn,request_id)
            if existing:
                return self._order(conn,existing['id'])
            require(request['status'] == 'APPROVED', '只有已批准申请可以创建订单')
            require(type(supplier_id) is int and supplier_id > 0 and items is not None and 0 < len(items) <= 100, '首次创建需供应商和订单明细')
            parsed = [OrderItem.model_validate(i) for i in items]
            require(len({i.product_id for i in parsed}) == len(parsed), '产品不可重复')
            supplier = self.suppliers.detail(conn,supplier_id,lock=True)
            require(supplier is not None and rules.supplier_status_check(supplier['status'])['passed'], '供应商不可用')
            request_items = {i['product_id']:i for i in self.repo.request_items(conn,request_id)}
            require(set(request_items) == {i.product_id for i in parsed}, '订单必须覆盖申请中的全部产品')
            total, chosen, candidates = Decimal('0'), [], None
            days = (request['required_delivery_date'] - date.today()).days
            categories = set()
            for item in sorted(parsed,key=lambda i:i.quote_id):
                req = request_items[item.product_id]
                product = self.suppliers.product(conn,item.product_id)
                require(product is not None, '有效产品不存在')
                categories.add(product['category'])
                quote = self.suppliers.quote(conn,item.quote_id)
                require(quote is not None and quote['supplier_id'] == supplier_id and quote['product_id'] == item.product_id, '报价与供应商或产品不匹配')
                require(item.quantity == req['quantity'], '订单数量必须与申请一致')
                checks = [rules.quantity_check(item.quantity,quote['available_quantity']),
                          rules.quote_validity_check(quote),rules.budget_limit_check(quote['unit_price'],req['max_unit_price']),
                          rules.delivery_deadline_check(quote['delivery_days'],days)]
                require(all(c['passed'] for c in checks), '; '.join(c['reason'] for c in checks if not c['passed']))
                total += item.quantity*quote['unit_price']
                chosen.append((item,quote['unit_price']))
                # Full pagination avoids undercounting distinct suppliers from repeated quotes.
                eligible, offset = set(), 0
                while True:
                    rows = self.suppliers.search(conn,item.product_id,item.quantity,req['max_unit_price'],days,date.today(),1000,offset)
                    eligible.update(r['supplier_id'] for r in rows)
                    if len(rows) < 1000:
                        break
                    offset += 1000
                candidates = eligible if candidates is None else candidates & eligible
            require(len(categories) == 1, 'Phase 1单供应商订单要求同一采购类别')
            require(rules.budget_limit_check(total,request['expected_budget'])['passed'], '订单超过申请金额')
            result = self.compliance.evaluate(conn,request['department_id'],supplier_id,next(iter(categories)),total,len(candidates))
            require(result['compliance_passed'], '采购合规检查失败: '+','.join(r['rule_code'] for r in result['failed_rules']))
            held = self.budget.repo.reserved_for_request(conn,request_id)
            require(held >= total, '已批准申请预占预算不足')
            order_id = self.repo.insert_order(conn,'PO-'+uuid4().hex,request,supplier_id,total)
            for item,price in chosen:
                self.repo.insert_order_item(conn,order_id,item,price)
                self.suppliers.consume(conn,item.quote_id,item.quantity)
            if held > total:
                self.budget.apply(conn,request,'RELEASE',held-total)
            self.repo.request_status(conn,request_id,'ORDER_CREATED')
            return self._order(conn,order_id)

    def update_purchase_order_status(self, purchase_order_id, status):
        require(status in ('CONFIRMED','CANCELLED'), '目标状态只能为CONFIRMED或CANCELLED')
        with self.db.transaction() as conn:
            initial = self.repo.order(conn,purchase_order_id)
            require(initial is not None, '订单不存在')
            # Global lock order: request -> order -> quotes -> budget.
            request = self.repo.request(conn,initial['request_id'],lock=True)
            order = self.repo.order(conn,purchase_order_id,lock=True)
            if order['status'] == status:
                return self._order(conn,purchase_order_id)
            require(order['status'] == 'CREATED', '已结束订单不能再次变更状态')
            if status == 'CANCELLED':
                for item in sorted(self.repo.order_items(conn,purchase_order_id),key=lambda i:i['quote_id'] or 0):
                    if item['quote_id'] is not None:
                        self.suppliers.quote(conn,item['quote_id'])
                        self.suppliers.restore(conn,item['quote_id'],item['quantity'])
                self.budget.apply(conn,request,'RELEASE',order['total_amount'])
                self.repo.request_status(conn,request['id'],'CANCELLED')
            else:
                self.budget.apply(conn,request,'COMMIT',order['total_amount'])
            self.repo.order_status(conn,purchase_order_id,status)
            return self._order(conn,purchase_order_id)
