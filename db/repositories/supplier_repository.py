from db.repositories.base import one, all_rows, execute

CANDIDATE_QUERY = '''SELECT q.id AS quote_id,q.supplier_id,s.supplier_name,s.status AS supplier_status,
 q.unit_price,q.unit_price * %s AS total_price,q.available_quantity,q.delivery_days,
 q.valid_until AS quote_valid_until,s.on_time_rate,s.quality_rate
 FROM supplier_quotes q JOIN suppliers s ON s.id=q.supplier_id
 WHERE q.product_id=%s AND q.status='ACTIVE' AND q.valid_from<=%s AND q.valid_until>=%s
 AND s.status='ACTIVE' AND q.available_quantity>=%s AND q.unit_price<=%s AND q.delivery_days<=%s
 AND EXISTS(SELECT 1 FROM supplier_qualifications k WHERE k.supplier_id=s.id AND k.qualification_type='BUSINESS_LICENSE'
 AND k.status='ACTIVE' AND k.valid_from<=%s AND k.valid_until>=%s)
 AND EXISTS(SELECT 1 FROM supplier_qualifications k WHERE k.supplier_id=s.id AND k.qualification_type='QUALITY_CERT'
 AND k.status='ACTIVE' AND k.valid_from<=%s AND k.valid_until>=%s)
 ORDER BY q.unit_price,q.delivery_days,q.id LIMIT %s OFFSET %s'''


class SupplierRepository:
    def product(self, conn, product):
        if type(product) is int:
            return one(conn, "SELECT * FROM products WHERE id=%s AND status='ACTIVE'", (product,))
        matches = all_rows(conn, "SELECT * FROM products WHERE (product_code=%s OR product_name=%s) AND status='ACTIVE' LIMIT 2", (product,product))
        return matches[0] if len(matches)==1 else None

    def search(self, conn, product_id, quantity, price, days, today, limit=100, offset=0):
        return all_rows(conn, CANDIDATE_QUERY, (quantity,product_id,today,today,quantity,price,days,today,today,today,today,limit,offset))

    def detail(self, conn, supplier_id, lock=False):
        return one(conn, 'SELECT * FROM suppliers WHERE id=%s' + (' FOR UPDATE' if lock else ''), (supplier_id,))

    def performance(self, conn, supplier_id, limit=100):
        return all_rows(conn, 'SELECT * FROM supplier_performance WHERE supplier_id=%s ORDER BY period DESC LIMIT %s', (supplier_id,limit))

    def quote(self, conn, quote_id):
        return one(conn, 'SELECT * FROM supplier_quotes WHERE id=%s FOR UPDATE', (quote_id,))

    def consume(self, conn, quote_id, quantity):
        execute(conn, 'UPDATE supplier_quotes SET available_quantity=available_quantity-%s WHERE id=%s', (quantity,quote_id))

    def restore(self, conn, quote_id, quantity):
        execute(conn, 'UPDATE supplier_quotes SET available_quantity=available_quantity+%s WHERE id=%s', (quantity,quote_id))
