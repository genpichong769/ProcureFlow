"""The only internal Agent contracts. Missing information stays null, never invented."""
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class RequirementFields(Model):
    department_code: str | None = Field(default=None, description='原文部门编码或完整名称，不得臆造映射')
    product_name: str | None = None
    product_code: str | None = None
    quantity: int | None = Field(default=None, gt=0, le=1000000)
    max_unit_price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    max_total_amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    max_delivery_days: int | None = Field(default=None, gt=0, le=365)
    required_delivery_date: date | None = None
    category: str | None = None
    reason: str | None = None
    supplier_id: int | None = Field(default=None, gt=0, description='仅用户明确限定供应商ID时提取')


class ProcurementRequirement(RequirementFields):
    request_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')


class BudgetInput(Model):
    request_id: str
    department_code: str
    requested_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class BudgetCheckResult(Model):
    request_id: str
    department_code: str
    total_budget: Decimal
    used_budget: Decimal
    reserved_budget: Decimal
    available_budget: Decimal
    requested_amount: Decimal
    budget_ok: bool
    remaining_after_purchase: Decimal
    reason: str


class SupplierCandidate(Model):
    quote_id: int
    supplier_id: int
    supplier_code: str
    supplier_name: str
    supplier_status: str
    product_id: int
    product_code: str
    product_name: str
    category: str
    unit_price: Decimal = Field(gt=0)
    total_price: Decimal = Field(gt=0)
    available_quantity: int = Field(ge=0)
    delivery_days: int = Field(gt=0)
    quote_valid_until: date
    on_time_rate: Decimal = Field(ge=0, le=1)
    quality_rate: Decimal = Field(ge=0, le=1)
    performance: list[dict] = Field(default_factory=list)
    price_score: Decimal | None = None
    delivery_score: Decimal | None = None
    on_time_score: Decimal | None = None
    quality_score: Decimal | None = None
    final_score: Decimal | None = None


class SupplierSearchResult(Model):
    request_id: str
    candidate_count: int
    candidates: list[SupplierCandidate]
    warnings: list[str] = Field(default_factory=list)


class ComplianceInput(Model):
    request_id: str
    department_code: str
    supplier_id: int = Field(gt=0)
    category: str
    total_amount: Decimal = Field(gt=0)
    valid_quote_count: int = Field(ge=0)


class ComplianceBatch(Model):
    request_id: str
    checks: list[ComplianceInput] = Field(min_length=1,max_length=1000)


class ComplianceResult(Model):
    request_id: str
    supplier_id: int
    compliance_passed: bool
    approval_chain: list[str]
    warnings: list[str]
    failed_rules: list[dict]
    required_quote_count: int
    qualifications: list[dict] = Field(default_factory=list)


class ProcurementProposal(Model):
    request_id: str
    requirement: ProcurementRequirement | None = None
    budget_result: BudgetCheckResult | None = None
    all_candidates: list[SupplierCandidate] = Field(default_factory=list)
    qualified_candidates: list[SupplierCandidate] = Field(default_factory=list)
    recommended_supplier: SupplierCandidate | None = None
    compliance_result: ComplianceResult | None = None
    compliance_results: list[ComplianceResult] = Field(default_factory=list)
    recommendation_reason: str = ''
    status: Literal['READY_FOR_APPROVAL','NO_BUDGET','NO_SUPPLIER','COMPLIANCE_FAILED','NEED_MORE_INFORMATION','ERROR']
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_type: str | None = None


class ExplanationPlan(Model):
    factors: list[Literal['PRICE','DELIVERY','ON_TIME','QUALITY']] = Field(min_length=1,max_length=4)
