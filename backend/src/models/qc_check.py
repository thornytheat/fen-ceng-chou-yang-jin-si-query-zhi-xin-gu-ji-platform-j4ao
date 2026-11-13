"""精度自检：相对误差 / CI 宽度 / 层最小样本 / 覆盖率 + 三角色复核链。"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, DECIMAL, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base
from src.models.approx_query import ApproxQuery


class QcCheck(Base):
    __tablename__ = "qc_checks"
    __table_args__ = (
        # 每个查询版本一条自检；历史版本各自保留自己的自检与复核链。
        UniqueConstraint("query_id", "revision_no", name="uq_qc_query_revision"),
        # code 不再唯一（按版本可重复），保留普通索引便于按编号检索。
        Index("ix_qc_code", "code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("approx_queries.id", ondelete="CASCADE"), nullable=False)
    # code 保留但不再做数据库唯一约束（改为 (query_id, revision_no) 唯一），便于历史版本并存
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    target_pct: Mapped[Decimal] = mapped_column(DECIMAL(5, 2), nullable=False)
    rel_error_pct: Mapped[Decimal] = mapped_column(DECIMAL(7, 4), nullable=False)
    ci_pct: Mapped[Decimal] = mapped_column(DECIMAL(7, 4), nullable=False)
    min_stratum_sample: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_pct: Mapped[Decimal] = mapped_column(DECIMAL(8, 4), nullable=False)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    review_state: Mapped[str] = mapped_column(String(16), nullable=False)
    signoffs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    query: Mapped[ApproxQuery] = relationship()
