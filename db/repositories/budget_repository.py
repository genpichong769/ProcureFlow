from db.repositories.base import one, all_rows, execute

BUDGET_QUERY = 'SELECT *, total_budget-used_budget-reserved_budget AS available_budget FROM department_budgets WHERE department_id=%s AND fiscal_year=%s'


class BudgetRepository:
    def department(self, conn, department):
        if type(department) is int:
            return one(conn, 'SELECT * FROM departments WHERE id=%s', (department,))
        matches = all_rows(conn, 'SELECT * FROM departments WHERE department_code=%s OR department_name=%s LIMIT 2', (department,department))
        return matches[0] if len(matches)==1 else None

    def get(self, conn, department_id, fiscal_year, lock=False):
        sql = BUDGET_QUERY + (' FOR UPDATE' if lock else '')
        return one(conn, sql, (department_id, fiscal_year))

    def transactions(self, conn, department_id, limit, offset):
        return all_rows(conn, 'SELECT * FROM budget_transactions WHERE department_id=%s ORDER BY transaction_time DESC,id DESC LIMIT %s OFFSET %s', (department_id, limit, offset))

    def save(self, conn, row):
        execute(conn, 'UPDATE department_budgets SET used_budget=%s,reserved_budget=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s', (row['used_budget'], row['reserved_budget'], row['id']))

    def record(self, conn, request, kind, amount, balance):
        execute(conn, 'INSERT INTO budget_transactions(department_id,fiscal_year,request_id,transaction_type,amount,balance_after,description) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                (request['department_id'],request['fiscal_year'],request['id'],kind,amount,balance,kind + '采购申请预算'))

    def reserved_for_request(self, conn, request_id):
        return one(conn, "SELECT COALESCE(SUM(CASE WHEN transaction_type='RESERVE' THEN amount WHEN transaction_type IN ('RELEASE','COMMIT') THEN -amount ELSE 0 END),0) AS amount FROM budget_transactions WHERE request_id=%s", (request_id,))['amount']
