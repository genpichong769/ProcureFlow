from datetime import date
import json
from decimal import Decimal
from db.connection import database
from db.repositories.budget_repository import BudgetRepository
from db.repositories.supplier_repository import SupplierRepository
from db.repositories.compliance_repository import ComplianceRepository
from services.errors import require
from services import rules


class ComplianceService:
    def __init__(self, db=database):
        self.db, self.repo = db, ComplianceRepository()

    def get_supplier_qualifications(self, supplier_id):
        with self.db.transaction() as conn:
            require(SupplierRepository().detail(conn,supplier_id) is not None, '供应商不存在')
            return self.repo.qualifications(conn,supplier_id)

    def get_procurement_rules(self, category):
        with self.db.transaction() as conn:
            return self.repo.rules(conn,category)

    def evaluate(self, conn, department, supplier_id, category, total_amount, valid_quote_count):
        amount = rules.money(total_amount)
        require(type(valid_quote_count) is int and valid_quote_count >= 0, '有效报价数必须为非负整数')
        dept = BudgetRepository().department(conn,department)
        require(dept is not None and dept['status'] == 'ACTIVE', '部门不存在或已停用')
        supplier = SupplierRepository().detail(conn,supplier_id)
        require(supplier is not None, '供应商不存在')
        qualifications = self.repo.qualifications(conn,supplier_id)
        results = [rules.supplier_status_check(supplier['status']),
                   rules.supplier_qualification_check(qualifications),
                   rules.minimum_quote_count_check(amount,valid_quote_count),
                   rules.outcome(supplier['category'] == category,'CATEGORY','供应商经营类别检查')]
        for rule in self.repo.rules(conn,category):
            if amount < rule['min_amount'] or (rule['max_amount'] is not None and amount >= rule['max_amount']):
                continue
            config = json.loads(rule['rule_config_json'])
            kind = rule['rule_type']
            if kind == 'MINIMUM_QUOTES':
                results.append(rules.minimum_quote_count_check(amount,valid_quote_count,Decimal(str(config['threshold'])),config['minimum']))
            elif kind == 'REQUIRED_QUALIFICATIONS':
                results.append(rules.supplier_qualification_check(qualifications,required=config['required']))
            elif kind == 'MAX_AMOUNT':
                results.append(rules.budget_limit_check(amount,config['limit']))
            elif kind == 'SUPPLIER_STATUS':
                results.append(rules.supplier_status_check(supplier['status']))
            else:
                results.append(rules.outcome(False,'UNKNOWN_RULE','未支持的启用规则: '+rule['rule_code']))
        failed = [r for r in results if not r['passed']]
        warnings = [f"资质 {q['qualification_type']} 将于 {q['valid_until']} 到期" for q in qualifications
                    if q['status'] == 'ACTIVE' and 0 <= (q['valid_until']-date.today()).days <= 30]
        return dict(compliance_passed=not failed,approval_chain=rules.approval_level_resolution(amount,self.repo.approvals(conn)),
                    warnings=warnings,failed_rules=failed)

    def evaluate_procurement_compliance(self, department, supplier_id, category, total_amount, valid_quote_count):
        # Advisory count supplied by caller; order creation independently recomputes it.
        with self.db.transaction() as conn:
            return self.evaluate(conn,department,supplier_id,category,total_amount,valid_quote_count)
