"""近似查询：HT 点估计 + 95% CI + 与全量真值对比 + 各层贡献。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, DECIMAL, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base
from src.models.dataset import Dataset
from src.models.sample_plan import SamplePlan


class ApproxQuery(Base):
    __tablename__ = "approx_queries"
    __table_args__ = (
        # 同一根查询下版本号唯一；根查询自身 root_query_id 为 NULL。
        UniqueConstraint("root_query_id", "revision_no", name="uq_query_revision"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("sample_plans.id", ondelete="CASCADE"), nullable=False)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    # --- 版本链：补样只对未达标层补未用样本，旧版本整行保留，不重建方案、不销毁已抽层 ---
    root_query_id: Mapped[int | None] = mapped_column(
        ForeignKey("approx_queries.id", ondelete="CASCADE"), nullable=True, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("approx_queries.id", ondelete="SET NULL"), nullable=True
    )
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    filter_strata: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    value_estimate_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ci_low_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ci_high_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rel_error_pct: Mapped[Decimal] = mapped_column(DECIMAL(7, 4), nullable=False)
    std_error_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    truth_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    truth_rel_error_pct: Mapped[Decimal] = mapped_column(DECIMAL(7, 4), nullable=False)
    strata_detail: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    sample_ms: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    truth_ms: Mapped[Decimal] = mapped_column(DECIMAL(10, 2), nullable=False)
    full_scan_baseline_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    run_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    plan: Mapped[SamplePlan] = relationship()
    dataset: Mapped[Dataset] = relationship()
