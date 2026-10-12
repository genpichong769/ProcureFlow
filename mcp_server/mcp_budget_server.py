from config import get_settings
from decimal import Decimal
from mcp_server.common import server, invoke
from services.budget_service import BudgetService


def create_server(db=None):
    mcp = server('ProcureFlowBudget',get_settings().mcp_budget_port)
    service = BudgetService(db) if db else BudgetService()

    @mcp.tool()
    async def get_department_budget(department: int | str, fiscal_year: int | None = None) -> dict:
        """按部门ID或编码查询年度预算和运行时计算的可用余额。"""
        return await invoke(service.get_department_budget,department,fiscal_year)

    @mcp.tool()
    async def get_budget_transactions(department: int | str, limit: int = 100, offset: int = 0) -> dict:
        """分页读取预算流水，最多1000条。"""
        return await invoke(service.get_budget_transactions,department,limit,offset)

    @mcp.tool()
    async def check_budget(department: int | str, amount: Decimal, fiscal_year: int | None = None) -> dict:
        """使用Decimal确定性检查预算；不产生预占。"""
        return await invoke(service.check_budget,department,amount,fiscal_year)

    return mcp


if __name__ == '__main__':
    create_server().run(transport='streamable-http')
