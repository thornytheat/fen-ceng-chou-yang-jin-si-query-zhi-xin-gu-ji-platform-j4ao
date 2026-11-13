"""精度自检：检查项 / 复核链。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.constants.enums import SignoffStage


class QcRunRequest(BaseModel):
    query_id: int
    target_pct: float | None = Field(default=None, ge=0.5, le=20)


class TopupRequest(BaseModel):
    query_id: int


class TopupPlanRowOut(BaseModel):
    code: str
    label: str
    population: int
    had: int
    min_required: int
    target: int
    add: int
    available_unused: int
    failed: bool
    feasible: bool
    reason: str


class TopupOut(BaseModel):
    id: int
    query_id: int
    query_code: str | None
    new_query_id: int | None
    new_query: dict | None = None
    idempotency_key: str
    status: str
    status_label: str
    plan: list[TopupPlanRowOut]
    applied: list[dict[str, Any]]
    reject_reason: str | None
    attempt_count: int
    created_by: str
    created_at: str
    action: str | None = None
    message: str | None = None


class QcCheckItemOut(BaseModel):
    code: str
    label: str
    actual: str
    threshold: str
    ok: bool
    note: str


class SignoffEntryOut(BaseModel):
    stage: str
    stage_label: str
    actor_email: str
    actor_name: str
    role: str
    decision: str
    note: str | None
    at: str


class SignoffRequest(BaseModel):
    stage: SignoffStage
    decision: str = Field(default="approve", pattern="^(approve|reject)$")
    note: str | None = Field(default=None, max_length=200)


class QcOut(BaseModel):
    id: int
    code: str
    query_id: int
    query_code: str
    revision_no: int
    is_latest: bool
    superseded_by_id: int | None = None
    dataset_name: str
    metric_label: str
    target_pct: float
    rel_error_pct: float
    ci_pct: float
    min_stratum_sample: int
    coverage_pct: float
    verdict: str
    verdict_label: str
    review_state: str
    review_state_label: str
    checks: list[QcCheckItemOut]
    signoffs: list[SignoffEntryOut]
    next_stage: str | None
    created_by: str
    created_at: str
    sample_size: int
    value_estimate: float
    true_value: float
    unit: str
    exportable: bool = False


class SignoffResultOut(BaseModel):
    qc: QcOut
    message: str
