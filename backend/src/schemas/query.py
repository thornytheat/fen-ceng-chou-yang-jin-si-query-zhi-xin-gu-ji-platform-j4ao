"""近似查询：运行请求 / 结果明细。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRunRequest(BaseModel):
    plan_id: int
    strata: list[str] = Field(default_factory=list, max_length=5)
    note: str | None = Field(default=None, max_length=200)


class StratumContributionOut(BaseModel):
    code: str
    label: str
    population: int
    sample_size: int
    topped_up: int = 0
    sample_mean: float
    contribution: float
    ci_half: float
    contribution_share_pct: float
    variance_share_pct: float
    verified: bool


class RevisionChainItem(BaseModel):
    id: int
    code: str
    revision_no: int
    is_latest: bool
    status: str
    sample_size: int
    rel_error_pct: float


class QueryOut(BaseModel):
    id: int
    code: str
    plan_id: int
    plan_name: str
    dataset_id: int
    dataset_code: str
    dataset_name: str
    metric_label: str
    unit: str
    filter_strata: list[str]
    revision_no: int
    root_query_id: int
    is_latest: bool
    superseded_by_id: int | None = None
    status: str
    status_label: str
    revision_chain: list[RevisionChainItem] = []
    sample_size: int
    value_estimate: float
    ci_low: float
    ci_high: float
    ci_half: float
    rel_error_pct: float
    true_value: float
    truth_rel_error_pct: float
    speed_ratio: float
    sample_ms: float
    truth_ms: float
    full_scan_baseline_ms: int
    run_by: str
    created_at: str
    strata_detail: list[StratumContributionOut]
    qc_id: int | None = None
    qc_verdict: str | None = None
    qc_review_state: str | None = None
    exportable: bool = False
