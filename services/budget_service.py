from datetime import date
from db.connection import database
from db.repositories.budget_repository import BudgetRepository
from db.repositories.procurement_repository import ProcurementRepository
from services.errors import require
from services import rules


class BudgetService:
    def __init__(self, db=database):
        self.db, self.repo, self.requests = db, BudgetRepository(), ProcurementRepository()

    def get_department_budget(self, department, fiscal_year=None):
        with self.db.transaction() as conn:
            dept = self.repo.department(conn, department)
            require(dept is not None, '部门不存在')
            row = self.repo.get(conn, dept['id'], fiscal_year or date.today().year)
            require(row is not None, '年度预算不存在')
            row['department_code'] = dept['department_code']
            row['department_name'] = dept['department_name']
            return row

    def get_budget_transactions(self, department, limit=100, offset=0):
        require(type(limit) is int and 1 <= limit <= 1000 and type(offset) is int and offset >= 0, '分页参数无效')
        with self.db.transaction() as conn:
            dept = self.repo.department(conn, department)
            require(dept is not None, '部门不存在')
            return self.repo.transactions(conn, dept['id'],limit,offset)

    def check_budget(self, department, amount, fiscal_year=None):
        row = self.get_department_budget(department, fiscal_year)
        return rules.budget_check(row['available_budget'], amount)

    def apply(self, conn, request, kind, amount):
        """Internal operation; caller holds the request row lock, then locks budget."""
        amount = rules.money(amount)
        row = self.repo.get(conn, request['department_id'],request['fiscal_year'],lock=True)
        require(row is not None, '年度预算不存在')
        held = self.repo.reserved_for_request(conn, request['id'])
        if kind == 'RESERVE':
            require(held == 0, '申请已经预占预算')
            require(rules.budget_check(row['available_budget'],amount)['passed'], '预算不足')
            row['reserved_budget'] += amount
        else:
            require(kind in ('RELEASE','COMMIT') and held >= amount, '申请预占预算不足')
            row['reserved_budget'] -= amount
            if kind == 'COMMIT':
                row['used_budget'] += amount
        self.repo.save(conn, row)
        self.repo.record(conn, request,kind,amount,row['total_budget']-row['used_budget']-row['reserved_budget'])

    def reserve(self, request_id):
        with self.db.transaction() as conn:
            request = self.requests.request(conn,request_id,lock=True)
            require(request is not None, '申请不存在')
            if request['status'] == 'PENDING_APPROVAL':
                return request
            require(request['status'] == 'DRAFT', '只有草稿可以提交并预占预算')
            self.apply(conn, request,'RESERVE',request['expected_budget'])
            self.requests.request_status(conn,request_id,'PENDING_APPROVAL')
            return self.requests.request(conn,request_id)

    def release(self, request_id):
        with self.db.transaction() as conn:
            request = self.requests.request(conn,request_id,lock=True)
            require(request is not None, '申请不存在')
            if request['status'] == 'CANCELLED':
                return request
            require(request['status'] in ('DRAFT','PENDING_APPROVAL','APPROVED'), '当前状态不可取消申请')
            held = self.repo.reserved_for_request(conn,request_id)
            if held:
                self.apply(conn,request,'RELEASE',held)
            self.requests.request_status(conn,request_id,'CANCELLED')
            return self.requests.request(conn,request_id)
