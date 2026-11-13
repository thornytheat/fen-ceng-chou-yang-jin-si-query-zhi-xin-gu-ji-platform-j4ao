"""补样单（sample top-up request）：自检未达标后的「只补未达标层」请求。

设计要点：
  * 一个补样单对应一次补样意图，带确定性幂等键 idempotency_key
    （= query 版本 id + 未达标层集合 + 每层目标样本量），重跑同一请求返回同一行，不新增样本/结果；
  * 状态机 running → done / rejected：中断后进程重启，凭幂等键找到 running 单即可续跑；
  * 容量不足在落任何新样本之前判定，直接置 rejected，不产生半成品；
  * 补样只从原数据（waybills）取该层「尚未使用」的样本，已抽好的层原样保留，方案不重建。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base


class SampleTopup(Base):
    __tablename__ = "sample_topups"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_topup_idempotency"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 发起补样时所基于的查询版本（未达标版本）
    query_id: Mapped[int] = mapped_column(
        ForeignKey("approx_queries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 补样完成后生成的新版本；rejected / 仍在 running 时为空
    new_query_id: Mapped[int | None] = mapped_column(
        ForeignKey("approx_queries.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # 每层补样决策：[{code, label, had, target, add, available_unused, feasible, reason?}]
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    # 实际补入样本数（done 后回填），结构同 plan 的 code → 实际补入条数
    applied: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    reject_reason: Mapped[str | None] = mapped_column(String(400))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
