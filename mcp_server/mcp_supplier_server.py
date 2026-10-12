from config import get_settings
from decimal import Decimal
from mcp_server.common import server, invoke
from services.supplier_service import SupplierService


def create_server(db=None):
    mcp = server('ProcureFlowSupplier',get_settings().mcp_supplier_port)
    service = SupplierService(db) if db else SupplierService()

    @mcp.tool()
    async def search_supplier_quotes(product: int | str, quantity: int, max_unit_price: Decimal,
                                     max_delivery_days: int, limit: int = 100, offset: int = 0) -> dict:
        """按产品ID/编码、数量、限价和交期筛选有效且有资质的供应商报价。"""
        return await invoke(service.search_supplier_quotes,product,quantity,max_unit_price,max_delivery_days,limit,offset)

    @mcp.tool()
    async def get_supplier_detail(supplier_id: int) -> dict:
        """查询供应商状态和履约评分。"""
        return await invoke(service.get_supplier_detail,supplier_id)

    @mcp.tool()
    async def get_supplier_performance(supplier_id: int, limit: int = 100) -> dict:
        """查询供应商历史月度履约统计。"""
        return await invoke(service.get_supplier_performance,supplier_id,limit)

    return mcp


if __name__ == '__main__':
    create_server().run(transport='streamable-http')
