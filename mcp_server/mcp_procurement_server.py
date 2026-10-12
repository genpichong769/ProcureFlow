from config import get_settings
from datetime import date
from mcp_server.common import server, invoke
from services.models import RequestItem, OrderItem
from services.procurement_service import ProcurementService


def create_server(db=None, enable_workflow_tools=False):
    mcp = server('ProcureFlowProcurement',get_settings().mcp_procurement_port)
    service = ProcurementService(db) if db else ProcurementService()

    @mcp.tool()
    async def create_purchase_request(requester_id: int, department_id: int, required_delivery_date: date,
                                       reason: str, items: list[RequestItem], request_no: str | None = None) -> dict:
        """真实创建采购草稿及明细；不自动审批。"""
        return await invoke(service.create_purchase_request,requester_id,department_id,required_delivery_date,
                            reason,[i.model_dump() for i in items],request_no)

    @mcp.tool()
    async def get_purchase_request(request_id: int) -> dict:
        """查询申请及全部行项目。"""
        return await invoke(service.get_purchase_request,request_id)

    @mcp.tool()
    async def submit_purchase_request(request_id: int) -> dict:
        """草稿提交待审批，原子预占预算；重复提交返回现有状态。"""
        return await invoke(service.budget.reserve,request_id)

    @mcp.tool()
    async def cancel_purchase_request(request_id: int) -> dict:
        """取消未下单申请并释放预占。已下单应取消订单。"""
        return await invoke(service.budget.release,request_id)

    @mcp.tool()
    async def create_purchase_order(request_id: int, supplier_id: int | None = None,
                                    items: list[OrderItem] | None = None) -> dict:
        """从已批准申请创建真实订单；报价决定单价；同request重试返回原PO。"""
        return await invoke(service.create_purchase_order,request_id,supplier_id,
                            None if items is None else [i.model_dump() for i in items])

    @mcp.tool()
    async def get_purchase_order(purchase_order_id: int) -> dict:
        """重新从数据库读取PO及明细。"""
        return await invoke(service.get_purchase_order,purchase_order_id)

    @mcp.tool()
    async def update_purchase_order_status(purchase_order_id: int, status: str) -> dict:
        """CREATED转CONFIRMED/COMMIT或CANCELLED/RELEASE；结束态不可逆。"""
        return await invoke(service.update_purchase_order_status,purchase_order_id,status)

    if enable_workflow_tools:
        @mcp.tool()
        async def validate_requester(requester_id: int, department: int | str) -> dict:
            """验证申请人启用状态、部门归属，并返回真实部门ID。"""
            return await invoke(service.validate_requester,requester_id,department)

        @mcp.tool()
        async def validate_approver(request_id: int, approver_id: int, required_role: str) -> dict:
            """验证审批人启用状态、部门归属与当前要求角色。"""
            return await invoke(service.validate_approver,request_id,approver_id,required_role)

        @mcp.tool()
        async def record_approval(request_id: int, approver_id: int, required_role: str,
                                  approval_level: int, decision: str, comment: str = '') -> dict:
            """幂等写入一层真实人工审批记录；不自动推进其他层级。"""
            return await invoke(service.record_approval,request_id,approver_id,required_role,
                                approval_level,decision,comment)

        @mcp.tool()
        async def release_request_budget(request_id: int) -> dict:
            """幂等释放待审批申请的全部预算预占；不修改申请状态。"""
            return await invoke(service.release_request_budget,request_id)

        @mcp.tool()
        async def set_purchase_request_approval(request_id: int, status: str) -> dict:
            """在审批链完成后标记APPROVED，或在释放预算后标记REJECTED。"""
            return await invoke(service.set_purchase_request_approval,request_id,status)

    return mcp


if __name__ == '__main__':
    create_server(enable_workflow_tools=True).run(transport='streamable-http')
