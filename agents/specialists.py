from decimal import Decimal, ROUND_DOWN
import json
from agents.schemas import (BudgetInput,BudgetCheckResult,ProcurementRequirement,SupplierCandidate,
    SupplierSearchResult,ComplianceBatch,ComplianceResult)
from agents.common import AgentFailure
from agents.llm import QwenGateway
from agents.mcp_client import ReadOnlyMCP, TOOLS
from config import get_settings


class BudgetAgent:
    name = 'BudgetAgent'
    def __init__(self, llm=None, mcp_factory=ReadOnlyMCP):
        self.llm,self.mcp_factory = llm or QwenGateway(),mcp_factory

    async def run(self, payload):
        task = BudgetInput.model_validate(payload)
        plan = await self.llm.select_tools(TOOLS['budget'],task.request_id,self.name)
        async with self.mcp_factory('budget',task.request_id,self.name).connect() as mcp:
            receipts = {}
            for name in plan:
                if name not in TOOLS['budget']: raise AgentFailure('FORBIDDEN_TOOL')
                args = {'department':task.department_code}
                if name=='check_budget':args['amount']=str(task.requested_amount)
                receipts[name] = await mcp.call(name,args)
            data,check = receipts['get_department_budget'],receipts['check_budget']
        # Source available amount and decision are taken from the Phase 1 tool, never from an LLM.
        return BudgetCheckResult(request_id=task.request_id,department_code=data['department_code'],
            total_budget=data['total_budget'],used_budget=data['used_budget'],reserved_budget=data['reserved_budget'],
            available_budget=data['available_budget'],requested_amount=task.requested_amount,budget_ok=check['passed'],
            remaining_after_purchase=Decimal(data['available_budget'])-task.requested_amount,reason=check['reason'])


class SupplierSourcingAgent:
    name = 'SupplierSourcingAgent'
    def __init__(self, llm=None, mcp_factory=ReadOnlyMCP):
        self.llm,self.mcp_factory = llm or QwenGateway(),mcp_factory

    async def run(self, payload):
        req = ProcurementRequirement.model_validate(payload)
        if not req.quantity or not req.max_delivery_days or not (req.max_unit_price or req.max_total_amount):
            raise AgentFailure('INCOMPLETE_SUPPLIER_QUERY')
        limits = [p for p in (req.max_unit_price,
            (req.max_total_amount/req.quantity).quantize(Decimal('.01'),rounding=ROUND_DOWN) if req.max_total_amount else None) if p is not None]
        ceiling = min(limits)
        if ceiling<=0:
            return SupplierSearchResult(request_id=req.request_id,candidate_count=0,candidates=[])
        plan = await self.llm.select_tools(TOOLS['supplier'],req.request_id,self.name)
        if set(plan)!=set(TOOLS['supplier']): raise AgentFailure('INVALID_TOOL_PLAN')
        async with self.mcp_factory('supplier',req.request_id,self.name).connect() as mcp:
            rows = []
            for page in range(get_settings().agent_max_candidate_pages):
                batch = await mcp.call('search_supplier_quotes',dict(product=req.product_code or req.product_name,
                    quantity=req.quantity,max_unit_price=str(ceiling),max_delivery_days=req.max_delivery_days,limit=100,offset=page*100))
                rows.extend(batch)
                if len(batch)<100:
                    break
            else:
                raise AgentFailure('CANDIDATE_PAGE_LIMIT')
            # Only MCP receipts populate facts. Detail and performance are fetched for each distinct supplier.
            supplier_ids = {r['supplier_id'] for r in rows}
            if req.supplier_id:
                supplier_ids.add(req.supplier_id)
            details,performance = {},{}
            for supplier_id in sorted(supplier_ids):
                # Search supplies IDs first; independent evidence follows the selected tool order.
                for name in plan:
                    if name=='get_supplier_detail':details[supplier_id] = await mcp.call(name,{'supplier_id':supplier_id})
                    elif name=='get_supplier_performance':performance[supplier_id] = await mcp.call(name,{'supplier_id':supplier_id,'limit':25})
            candidates = []
            for row in rows:
                row['supplier_code'] = details[row['supplier_id']]['supplier_code']
                row['performance'] = performance[row['supplier_id']]
                candidates.append(SupplierCandidate.model_validate(row))
        return SupplierSearchResult(request_id=req.request_id,candidate_count=len(candidates),candidates=candidates,
            warnings=[] if candidates else ['没有满足库存、报价、资质和交期的候选'])


class ComplianceApprovalAgent:
    name = 'ComplianceApprovalAgent'
    def __init__(self, llm=None, mcp_factory=ReadOnlyMCP):
        self.llm,self.mcp_factory = llm or QwenGateway(),mcp_factory

    async def run(self, payload):
        batch = ComplianceBatch.model_validate(payload)
        plan = await self.llm.select_tools(TOOLS['compliance'],batch.request_id,self.name)
        if set(plan)!=set(TOOLS['compliance']): raise AgentFailure('INVALID_TOOL_PLAN')
        results, rule_cache, qualification_cache = [],{},{}
        async with self.mcp_factory('compliance',batch.request_id,self.name).connect() as mcp:
            for task in batch.checks:
                if task.request_id!=batch.request_id:
                    raise AgentFailure('REQUEST_ID_MISMATCH')
                for name in plan:
                    if name=='get_supplier_qualifications' and task.supplier_id not in qualification_cache:
                        qualification_cache[task.supplier_id] = await mcp.call(name,{'supplier_id':task.supplier_id})
                    elif name=='get_procurement_rules' and task.category not in rule_cache:
                        rule_cache[task.category] = await mcp.call(name,{'category':task.category})
                result = await mcp.call('evaluate_procurement_compliance',dict(department=task.department_code,
                    supplier_id=task.supplier_id,category=task.category,total_amount=str(task.total_amount),valid_quote_count=task.valid_quote_count))
                needed = 3 if task.total_amount>100000 else 0
                for rule in rule_cache[task.category]:
                    if Decimal(str(rule['min_amount']))<=task.total_amount and (rule['max_amount'] is None or task.total_amount<Decimal(str(rule['max_amount']))):
                        config = json.loads(rule['rule_config_json'])
                        if rule['rule_type']=='MINIMUM_QUOTES' and task.total_amount>Decimal(str(config['threshold'])):
                            needed = max(needed,int(config['minimum']))
                results.append(ComplianceResult(request_id=task.request_id,supplier_id=task.supplier_id,
                    required_quote_count=needed,qualifications=qualification_cache[task.supplier_id],**result))
        return results
