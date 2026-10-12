from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workflow_id: str = Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    approver_id: int = Field(gt=0,strict=True)
    approver_role: str = Field(min_length=1,max_length=40)
    decision: Literal['APPROVE','REJECT']
    comment: str = Field(default='',max_length=1000)


class RecoveryDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workflow_id: str = Field(min_length=1,max_length=100)
    retry: Literal[True]
