from db.repositories.base import all_rows


class ComplianceRepository:
    def qualifications(self, conn, supplier_id):
        return all_rows(conn, 'SELECT * FROM supplier_qualifications WHERE supplier_id=%s ORDER BY qualification_type', (supplier_id,))

    def rules(self, conn, category):
        return all_rows(conn, 'SELECT * FROM procurement_rules WHERE enabled=TRUE AND (category IS NULL OR category=%s) ORDER BY priority,id', (category,))

    def approvals(self, conn):
        return all_rows(conn, 'SELECT * FROM approval_rules WHERE enabled=TRUE ORDER BY min_amount')
