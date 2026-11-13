"""精度自检 controller。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from src.services import qc_service, topup_service


def list_checks(db: Session, limit: int = 40) -> dict:
    items = [qc_service.qc_out(db, row) for row in qc_service.list_checks(db, limit)]
    return {"items": items, "total": len(items)}


def get_check(db: Session, qc_id: int) -> dict:
    return qc_service.qc_out(db, qc_service.get_check(db, qc_id))


def run_check(db: Session, payload, actor: dict, ip: str | None = None) -> dict:
    row = qc_service.run_check(db, payload.query_id, payload.target_pct, actor, ip)
    db.commit()
    return qc_service.qc_out(db, qc_service.get_check(db, row.id))


def sign_off(db: Session, qc_id: int, payload, actor: dict, ip: str | None = None) -> dict:
    qc_service.sign_off(db, qc_id, payload.stage, payload.decision, payload.note, actor, ip)
    db.commit()
    return {"qc": qc_service.qc_out(db, qc_service.get_check(db, qc_id)), "message": "复核已记录"}


def run_topup(db: Session, payload, actor: dict, ip: str | None = None) -> dict:
    topup, action = topup_service.request_topup(db, payload.query_id, actor, ip)
    db.commit()
    return topup_service.topup_out(db, topup_service.get_topup(db, topup.id), action)


def list_topups(db: Session, limit: int = 40) -> dict:
    rows = topup_service.list_topups(db, limit)
    return {"items": [topup_service.topup_out(db, row) for row in rows], "total": len(rows)}
