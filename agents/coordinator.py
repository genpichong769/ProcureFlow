"""Proposal-only coordinator. Its only business dependency is an A2A transport."""
from datetime import date
from decimal import Decimal
from uuid import uuid4
from agents.schemas import (ProcurementRequirement,ProcurementProposal,BudgetCheckResult,
    SupplierSearchResult,ComplianceResult)
from agents.common import AgentFailure, trace
from agents.llm import QwenGateway
from agents.requirement_validation import validate_amounts
from config import get_settings


def prepare_requirement(req):
    missing = []
    if not req.department_code: missing.append('department_code')
    if not (req.product_code or req.product_name): missing.append('product_name')
    if req.quantity is None: missing.append('quantity')
    if req.max_unit_price is None and req.max_total_amount is None: missing.append('budget')
    if req.required_delivery_date:
        days = (req.required_delivery_date-date.today()).days
        if days<=0: raise AgentFailure('INVALID_DELIVERY_DATE')
        req.max_delivery_days = min(req.max_delivery_days,days) if req.max_delivery_days else days
    if req.max_delivery_days is None: missing.append('delivery_deadline')
    if not missing:
        cap = req.max_unit_price*req.quantity if req.max_unit_price else req.max_total_amount
        req.max_total_amount = min(cap,req.max_total_amount) if req.max_total_amount else cap
    return missing


def hard_filter(candidates,req):
    return [c for c in candidates if c.supplier_status=='ACTIVE' and c.available_quantity>=req.quantity
        and c.total_price==c.unit_price*req.quantity and c.total_price<=req.max_total_amount
        and (req.max_unit_price is None or c.unit_price<=req.max_unit_price)
        and c.delivery_days<=req.max_delivery_days and c.quote_valid_until>=date.today()
        and (req.category is None or c.category==req.category)
        and (req.product_code is None or c.product_code==req.product_code)]


def rank(candidates):
    if not candidates: return []
    config = get_settings()
    weights = [Decimal(str(getattr(config,'score_'+name+'_weight'))) for name in ('price','delivery','on_time','quality')]
    if sum(weights)!=1 or any(w<0 for w in weights):
        raise AgentFailure('INVALID_SCORING_WEIGHTS')
    minimum_price = min(c.unit_price for c in candidates)
    minimum_days = min(c.delivery_days for c in candidates)
    ranked = []
    for original in candidates:
        c = original.model_copy(deep=True)
        values = [minimum_price/c.unit_price*100,Decimal(minimum_days)/c.delivery_days*100,c.on_time_rate*100,c.quality_rate*100]
        c.price_score,c.delivery_score,c.on_time_score,c.quality_score = [v.quantize(Decimal('.000001')) for v in values]
        c.final_score = sum(w*v for w,v in zip(weights,values)).quantize(Decimal('.000001'))
        ranked.append(c)
    return sorted(ranked,key=lambda c:(-c.final_score,c.total_price,c.delivery_days,c.supplier_id,c.quote_id))


def explain(candidate,plan,chain):
    facts = dict(PRICE=f'总价{candidate.total_price:.2f}元',DELIVERY=f'交期{candidate.delivery_days}天',
        ON_TIME=f'准时率{candidate.on_time_rate*100:.2f}%',QUALITY=f'质量合格率{candidate.quality_rate*100:.2f}%')
    details = '、'.join(facts[k] for k in dict.fromkeys(plan.factors))
    approval = ' → '.join(chain) if chain else '普通采购流程'
    return f'建议选择{candidate.supplier_name}（{candidate.supplier_code}）：{details}，确定性综合评分{candidate.final_score:.6f}。硬规则及合规预检通过，后续审批路径：{approval}。当前仅生成建议，尚未审批或下单。'


class ProcurementCoordinatorAgent:
    name = 'ProcurementCoordinatorAgent'
    def __init__(self,llm=None,transport=None):
        from agents.a2a_transport import A2ATransport
        self.llm,self.transport = llm or QwenGateway(),transport or A2ATransport()

    async def run(self,payload):
        request_id = payload.get('request_id') or 'REQ-'+uuid4().hex
        proposal = ProcurementProposal(request_id=request_id,status='ERROR')
        trace(request_id,self.name,'REQUEST_START')
        try:
            if 'text' in payload:
                if not isinstance(payload['text'],str) or not 1<=len(payload['text'])<=4000:
                    raise AgentFailure('INVALID_USER_INPUT')
                fields = await self.llm.extract(payload['text'],request_id)
                validation = validate_amounts(payload['text'],fields)
                fields = validation.fields
                trace(request_id,self.name,'NUMERIC_VALIDATION',
                      status='NEEDS_CLARIFICATION' if validation.ambiguous else 'SUCCESS',
                      error_type='AMBIGUOUS_BUDGET' if validation.ambiguous else None)
                req = ProcurementRequirement(request_id=request_id,**fields.model_dump())
            else:
                req = ProcurementRequirement.model_validate({**payload['requirement'],'request_id':request_id})
            proposal.requirement = req
            missing = prepare_requirement(req)
            if missing:
                proposal.status,proposal.missing_fields = 'NEED_MORE_INFORMATION',missing
                labels = dict(department_code='部门编码或完整名称',product_name='产品名称或编码',quantity='数量',budget='预算',delivery_deadline='期望交期')
                proposal.recommendation_reason = '缺少：'+'、'.join(labels[k] for k in missing)+'。请补充后再查询。'
                return proposal
            budget = await self.transport.call('budget',dict(request_id=request_id,department_code=req.department_code,
                                                              requested_amount=str(req.max_total_amount)))
            proposal.budget_result = BudgetCheckResult.model_validate(budget)
            if proposal.budget_result.request_id!=request_id or proposal.budget_result.requested_amount!=req.max_total_amount:
                raise AgentFailure('BUDGET_IDENTITY_MISMATCH')
            req.department_code = proposal.budget_result.department_code
            if not proposal.budget_result.budget_ok:
                proposal.status,proposal.recommendation_reason = 'NO_BUDGET',proposal.budget_result.reason
                return proposal
            search = SupplierSearchResult.model_validate(await self.transport.call('supplier',req.model_dump(mode='json')))
            if search.request_id!=request_id or search.candidate_count!=len(search.candidates):
                raise AgentFailure('SUPPLIER_IDENTITY_MISMATCH')
            proposal.all_candidates,proposal.warnings = search.candidates,search.warnings
            valid = hard_filter(search.candidates,req)
            quote_count = len({c.supplier_id for c in valid})
            targets = [c for c in valid if req.supplier_id is None or c.supplier_id==req.supplier_id]
            checks = [dict(request_id=request_id,department_code=req.department_code,supplier_id=c.supplier_id,
                           category=c.category,total_amount=str(c.total_price),valid_quote_count=quote_count) for c in targets]
            # Explicit requested supplier is checked even when Phase 1 sourcing rejects it.
            if not checks and req.supplier_id and req.category:
                checks = [dict(request_id=request_id,department_code=req.department_code,supplier_id=req.supplier_id,
                               category=req.category,total_amount=str(req.max_total_amount),valid_quote_count=quote_count)]
            if not checks:
                proposal.status,proposal.recommendation_reason = 'NO_SUPPLIER','未找到满足硬规则的供应商报价。'
                return proposal
            results = await self.transport.call('compliance',dict(request_id=request_id,checks=checks))
            proposal.compliance_results = [ComplianceResult.model_validate(r) for r in results]
            if len(results)!=len(checks): raise AgentFailure('INCOMPLETE_COMPLIANCE_RESPONSE')
            for sent,received in zip(checks,proposal.compliance_results):
                if received.supplier_id!=sent['supplier_id'] or received.request_id!=request_id:
                    raise AgentFailure('COMPLIANCE_IDENTITY_MISMATCH')
            qualified = [c for c,r in zip(targets,proposal.compliance_results) if r.compliance_passed]
            # Phase 1 tool is authoritative; no language-model override path exists.
            if not qualified:
                failed = next((r for r in proposal.compliance_results if not r.compliance_passed),None)
                proposal.compliance_result = failed
                proposal.status = 'COMPLIANCE_FAILED' if failed else 'NO_SUPPLIER'
                proposal.recommendation_reason = '供应商未通过合规预检。' if failed else '无合格报价。'
                return proposal
            proposal.qualified_candidates = rank(qualified)
            selected = proposal.qualified_candidates[0]
            result = next(r for c,r in zip(targets,proposal.compliance_results) if c.quote_id==selected.quote_id)
            plan = await self.llm.explanation(selected,request_id)
            proposal.recommendation_reason = explain(selected,plan,result.approval_chain)
            proposal.recommended_supplier,proposal.compliance_result = selected,result
            proposal.status = 'READY_FOR_APPROVAL'
            return proposal
        except AgentFailure as exc:
            proposal.status,proposal.error_type = 'ERROR',exc.code
            proposal.recommendation_reason = '采购建议生成失败：'+exc.code+'；未进行审批或下单。'
            return proposal
        except Exception:
            proposal.status,proposal.error_type = 'ERROR','INVALID_AGENT_RESPONSE'
            proposal.recommendation_reason = '上游结构化结果无效；未生成推荐。'
            return proposal
        finally:
            trace(request_id,self.name,'REQUEST_END',status=proposal.status,error_type=proposal.error_type)
