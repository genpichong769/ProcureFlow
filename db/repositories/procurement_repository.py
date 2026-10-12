from db.repositories.base import one, all_rows, execute

ORDER_QUERY = 'SELECT * FROM purchase_orders WHERE request_id=%s'


class ProcurementRepository:
    def request(self, conn, request_id, lock=False):
        return one(conn, 'SELECT * FROM purchase_requests WHERE id=%s' + (' FOR UPDATE' if lock else ''), (request_id,))

    def request_items(self, conn, request_id):
        return all_rows(conn, 'SELECT * FROM purchase_request_items WHERE request_id=%s ORDER BY product_id', (request_id,))

    def request_by_no(self, conn, request_no, lock=False):
        return one(conn, 'SELECT * FROM purchase_requests WHERE request_no=%s' + (' FOR UPDATE' if lock else ''), (request_no,))

    def request_status(self, conn, request_id, status):
        execute(conn, 'UPDATE purchase_requests SET status=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s', (status,request_id))

    def employee(self, conn, employee_id):
        return one(conn, 'SELECT * FROM employees WHERE id=%s', (employee_id,))

    def approval(self, conn, request_id, approval_level, lock=False):
        return one(conn, 'SELECT * FROM approval_records WHERE request_id=%s AND approval_level=%s' + (' FOR UPDATE' if lock else ''),
                   (request_id,approval_level))

    def insert_approval(self, conn, request_id, approver_id, approval_level, decision, comment):
        return execute(conn, '''INSERT INTO approval_records(request_id,approver_id,approval_level,decision,comment,decided_at)
            VALUES(%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)''',
            (request_id,approver_id,approval_level,decision,comment))

    def insert_request(self, conn, number, data, fiscal_year, amount):
        return execute(conn, "INSERT INTO purchase_requests(request_no,requester_id,department_id,fiscal_year,expected_budget,required_delivery_date,reason,status) VALUES(%s,%s,%s,%s,%s,%s,%s,'DRAFT')", (number,data.requester_id,data.department_id,fiscal_year,amount,data.required_delivery_date,data.reason))

    def insert_request_item(self, conn, request_id, item):
        execute(conn, 'INSERT INTO purchase_request_items(request_id,product_id,quantity,max_unit_price,max_total_price) VALUES(%s,%s,%s,%s,%s)', (request_id,item.product_id,item.quantity,item.max_unit_price,item.quantity*item.max_unit_price))

    def order_by_request(self, conn, request_id):
        return one(conn, ORDER_QUERY, (request_id,))

    def order(self, conn, order_id, lock=False):
        return one(conn, 'SELECT * FROM purchase_orders WHERE id=%s' + (' FOR UPDATE' if lock else ''), (order_id,))

    def order_items(self, conn, order_id):
        return all_rows(conn, 'SELECT * FROM purchase_order_items WHERE purchase_order_id=%s ORDER BY product_id', (order_id,))

    def insert_order(self, conn, number, request, supplier_id, total):
        return execute(conn, "INSERT INTO purchase_orders(po_no,request_id,department_id,supplier_id,total_amount,status) VALUES(%s,%s,%s,%s,%s,'CREATED')", (number,request['id'],request['department_id'],supplier_id,total))

    def insert_order_item(self, conn, order_id, item, price):
        execute(conn, 'INSERT INTO purchase_order_items(purchase_order_id,product_id,quote_id,quantity,unit_price,total_price) VALUES(%s,%s,%s,%s,%s,%s)', (order_id,item.product_id,item.quote_id,item.quantity,price,item.quantity*price))

    def order_status(self, conn, order_id, status):
        execute(conn, 'UPDATE purchase_orders SET status=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s', (status,order_id))
