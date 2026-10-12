from config import get_settings
from decimal import Decimal
from mcp_server.common import server, invoke
from services.compliance_service import ComplianceService


def create_server(db=None):
    mcp = server('ProcureFlowCompliance',get_settings().mcp_compliance_port)
    service = ComplianceService(db) if db else ComplianceService()

    @mcp.tool()
    async def get_supplier_qualifications(supplier_id: int) -> dict:
        """返回供应商全部资质及有效期。"""
        return await invoke(service.get_supplier_qualifications,supplier_id)

    @mcp.tool()
    async def get_procurement_rules(category: str) -> dict:
        """返回已启用的全局及分类采购规则。"""
        return await invoke(service.get_procurement_rules,category)

    @mcp.tool()
    async def evaluate_procurement_compliance(department: int | str, supplier_id: int, category: str,
                                              total_amount: Decimal, valid_quote_count: int) -> dict:
        """确定性预检及审批链；报价数为调用方提供，创建订单时会重新核验。"""
        return await invoke(service.evaluate_procurement_compliance,department,supplier_id,category,total_amount,valid_quote_count)

    return mcp


if __name__ == '__main__':
    create_server().run(transport='streamable-http')
