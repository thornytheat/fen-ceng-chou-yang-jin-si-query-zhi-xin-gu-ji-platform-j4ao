"""近似查询 controller。"""
from __future__ import annotations

from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.constants.enums import ReviewState
from src.models.qc_check import QcCheck
from src.services import export_service, qc_service, query_service
from src.utils.errors import AppError


def list_queries(db: Session, plan_id: int | None = None, limit: int = 40) -> dict:
    rows = query_service.list_queries(db, plan_id, limit)
    items = [query_service.query_out(db, row) for row in rows]
    return {"items": items, "total": len(items)}


def get_query(db: Session, query_id: int) -> dict:
    return query_service.query_out(db, query_service.get_query(db, query_id))


def run_query(db: Session, payload, actor: dict, ip: str | None = None) -> dict:
    row = query_service.run_query(db, payload.plan_id, payload.strata, payload.note, actor, ip)
    db.commit()
    return query_service.query_out(db, query_service.get_query(db, row.id))


def export_query(db: Session, query_id: int) -> Response:
    row = query_service.get_query(db, query_id)
    qc = db.scalar(select(QcCheck).where(QcCheck.query_id == row.id))
    # 页面、自检、导出三处口径一致：只有「最新版本 + 自检达标 + 三级复核通过」可导出。
    if qc is None:
        raise AppError("EXPORT_NOT_READY", 409, detail="该版本尚未完成精度自检")
    if not row.is_latest:
        raise AppError("EXPORT_NOT_READY", 409, detail="旧版本已被替代，仅最新复核通过版本可导出")
    if qc.verdict != "pass" or qc.review_state != ReviewState.CONFIRMED.value:
        raise AppError("EXPORT_NOT_READY", 409, detail="自检达标且三级复核全部通过后才能导出")
    filename, content = export_service.build_estimate_markdown(row, qc)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
