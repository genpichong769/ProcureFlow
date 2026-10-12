from datetime import date
from db.connection import database
from db.repositories.supplier_repository import SupplierRepository
from services.errors import require
from services.rules import money


class SupplierService:
    def __init__(self, db=database):
        self.db, self.repo = db, SupplierRepository()

    def search_supplier_quotes(self, product, quantity, max_unit_price, max_delivery_days, limit=100, offset=0):
        require(type(quantity) is int and 0 < quantity <= 1000000, '数量必须为正整数')
        require(type(max_delivery_days) is int and 0 < max_delivery_days <= 365, '交期范围为1到365天')
        require(type(limit) is int and 1 <= limit <= 1000 and type(offset) is int and offset >= 0, '分页参数无效')
        price = money(max_unit_price)
        with self.db.transaction() as conn:
            product_row = self.repo.product(conn,product)
            require(product_row is not None, '有效产品不存在；请使用产品ID或编码')
            rows = self.repo.search(conn,product_row['id'],quantity,price,max_delivery_days,date.today(),limit,offset)
            for row in rows:
                row.update(product_id=product_row['id'],product_code=product_row['product_code'],
                           product_name=product_row['product_name'],category=product_row['category'])
            return rows

    def get_supplier_detail(self, supplier_id):
        with self.db.transaction() as conn:
            row = self.repo.detail(conn,supplier_id)
            require(row is not None, '供应商不存在')
            return row

    def get_supplier_performance(self, supplier_id, limit=100):
        require(type(limit) is int and 1 <= limit <= 1000, '分页参数无效')
        with self.db.transaction() as conn:
            require(self.repo.detail(conn,supplier_id) is not None, '供应商不存在')
            return self.repo.performance(conn,supplier_id,limit)
