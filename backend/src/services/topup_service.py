"""补样服务：自检未达标后，只给未达标层从原数据补入「未使用」样本。

与旧做法的区别（对应需求）：
  * 不重建整套方案、不作废已抽好的层：通过的层 n_h 原样保留，只动未达标层；
  * 补入的是原数据表 waybills 里该层 sample_rank 排在已用样本之后、从未被抽过的行；
  * 容量仍不足（未用行数 < 还需行数）时，在写入任何新样本之前直接拒绝（rejected）；
  * 补样后重算 HT 点估计与置信区间，并重新跑三级复核链（新版本各自一条 QC）；
  * 补样单带确定性幂等键：重跑同一请求返回同一补样单，不新增样本或结果；
    running 单可续跑，done/rejected 单直接回放结论。

本模块上半部分是不依赖 DB/Session 的纯函数（plan_stratum_topups / idempotency_key_for），
单测可直接覆盖；下半部分是事务编排。
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.constants.enums import QueryStatus, ReviewState, TopupStatus
from src.models.approx_query import ApproxQuery
from src.models.qc_check import QcCheck
from src.models.sample_topup import SampleTopup
from src.services import audit_service, dataset_service, estimation_service, qc_service
from src.services.topup_planning import (
    StratumTopupContext,
    idempotency_key_for,
    plan_stratum_topups,
)
from src.utils.errors import AppError

# 该层已抽 n_h 行（按 sample_rank 升序取最小 n_h 行），补样从第 n_h 行之后继续取，
# 天然只会拿到「未使用」样本，且与既有抽样的确定性口径完全一致。
UNUSED_SAMPLE_SQL = text(
    """
    SELECT value_minor
    FROM waybills
    WHERE dataset_id = :dataset_id AND stratum_code = :code
    ORDER BY sample_rank
    LIMIT :limit OFFSET :offset
    """
)


# ============================================================ DB 事务编排


def _next_revision_code(db: Session, root: ApproxQuery, revision_no: int) -> str:
    base_code = root.code if root.root_query_id == root.id else (
        db.get(ApproxQuery, root.root_query_id).code if root.root_query_id else root.code
    )
    return f"{base_code}-r{revision_no}"


def list_topups(db: Session, limit: int = 40) -> list[SampleTopup]:
    return list(db.scalars(select(SampleTopup).order_by(SampleTopup.id.desc()).limit(limit)))


def get_topup(db: Session, topup_id: int) -> SampleTopup:
    row = db.get(SampleTopup, topup_id)
    if row is None:
        raise AppError("NOT_FOUND", 404, detail=f"topup {topup_id}")
    return row


def _build_contexts(query: ApproxQuery, qc: QcCheck, min_required: int) -> list[StratumTopupContext]:
    failed_codes: set[str] = set()
    for check in qc.checks or []:
        # 最小层样本检查不通过时，从 actual 文本不可靠地反推层，故改由各层 n_h 与下限比较
        if check.get("code") == "min_stratum_sample" and not check.get("ok"):
            for item in query.strata_detail or []:
                if int(item.get("sample_size", 0)) < min_required:
                    failed_codes.add(item.get("code"))
    ci_check_failed = any(
        check.get("code") == "ci_within_standard" and not check.get("ok") for check in (qc.checks or [])
    )
    rel_check_failed = any(
        check.get("code") == "rel_error_vs_standard" and not check.get("ok") for check in (qc.checks or [])
    )
    # 全局 CI / 相对误差未达标时，对仍有未用样本的层做补样；已全抽（n_h=N_h）的层无样本可补。
    global_failed = ci_check_failed or rel_check_failed
    contexts: list[StratumTopupContext] = []
    for item in query.strata_detail or []:
        code = item.get("code")
        had = int(item.get("sample_size", 0))
        population = int(item.get("population", 0))
        contexts.append(
            StratumTopupContext(
                code=code,
                label=item.get("label", code),
                population=population,
                had=had,
                min_required=min_required,
                ci_half_pct=float(item.get("ci_half_pct", 0.0) or 0.0),
                failed=(code in failed_codes) or (global_failed and had < population),
            )
        )
    return contexts


def _load_existing_samples(db: Session, query: ApproxQuery) -> dict[str, list[float]]:
    """取回旧版本每层已抽样本（按 rank 最小 n_h 行），与补入样本拼接后整体重算。"""
    samples: dict[str, list[float]] = {}
    for item in query.strata_detail or []:
        code = item["code"]
        had = int(item.get("sample_size", 0))
        if had <= 0:
            samples[code] = []
            continue
        values = db.execute(
            text(
                "SELECT value_minor FROM waybills "
                "WHERE dataset_id = :dataset_id AND stratum_code = :code "
                "ORDER BY sample_rank LIMIT :limit"
            ),
            {"dataset_id": query.dataset_id, "code": code, "limit": had},
        ).scalars().all()
        samples[code] = [float(v) for v in values]
    return samples


def _create_revision(
    db: Session,
    base: ApproxQuery,
    plan_rows: list[dict],
    actor: dict,
) -> ApproxQuery:
    """按补样决策取未用样本、重算 HT 估计与 CI，生成新版本查询行（旧行不动）。"""
    import time
    from datetime import datetime

    dataset = base.dataset
    wanted = list(base.filter_strata or [])
    meta = dataset_service.strata_inputs(dataset, wanted or None)
    samples = _load_existing_samples(db, base)
    applied: list[dict] = []

    for row in plan_rows:
        code = row["code"]
        add = int(row["add"])
        if add <= 0:
            applied.append({"code": code, "added": 0})
            continue
        had = int(row["had"])
        extra = db.execute(
            UNUSED_SAMPLE_SQL,
            {"dataset_id": dataset.id, "code": code, "limit": add, "offset": had},
        ).scalars().all()
        extra_values = [float(v) for v in extra]
        if len(extra_values) < add:
            # 兜底：并发下余量被占用等极端情况，不应静默少抽
            raise AppError("TOPUP_CAPACITY", 409, detail=f"stratum {code} unused rows exhausted")
        samples[code] = list(samples.get(code, [])) + extra_values
        applied.append({"code": code, "added": len(extra_values)})

    started = time.perf_counter()
    estimate = estimation_service.ht_estimate(meta, samples, float(base.plan.confidence_level))
    sample_ms = (time.perf_counter() - started) * 1000.0

    # 同口径全量真值（与原查询一致，不随补样改变）
    if wanted:
        placeholders = ", ".join(f":s{i}" for i in range(len(wanted)))
        params: dict = {"dataset_id": dataset.id}
        for i, code in enumerate(wanted):
            params[f"s{i}"] = code
        truth_row = db.execute(
            text(
                "SELECT COALESCE(SUM(value_minor), 0) AS total, COUNT(*) AS row_count FROM waybills "
                f"WHERE dataset_id = :dataset_id AND stratum_code IN ({placeholders})"
            ),
            params,
        ).one()
    else:
        truth_row = db.execute(
            text("SELECT COALESCE(SUM(value_minor), 0) AS total, COUNT(*) AS row_count FROM waybills "
                 "WHERE dataset_id = :dataset_id"),
            {"dataset_id": dataset.id},
        ).one()
    truth_minor = int(truth_row.total or 0)
    if truth_minor <= 0:
        raise AppError("DATASET_EMPTY", 422, detail="no detail rows for the selected scope")
    compare = estimation_service.compare_with_truth(estimate["estimate_minor"], truth_minor)

    root_id = base.root_query_id or base.id
    next_no = int(base.revision_no or 1) + 1
    root_row = base if base.root_query_id == base.id else db.get(ApproxQuery, root_id)
    revision = ApproxQuery(
        plan_id=base.plan_id,
        dataset_id=dataset.id,
        code=_next_revision_code(db, root_row or base, next_no),
        root_query_id=root_id,
        revision_no=next_no,
        superseded_by_id=None,
        is_latest=True,
        filter_strata=list(base.filter_strata or []),
        sample_size=int(estimate["sample_size"]),
        value_estimate_minor=int(round(estimate["estimate_minor"])),
        ci_low_minor=int(round(estimate["ci_low_minor"])),
        ci_high_minor=int(round(estimate["ci_high_minor"])),
        rel_error_pct=round(estimate["rel_error_pct"], 4),
        std_error_minor=int(round(estimate["std_error_minor"])),
        truth_total_minor=truth_minor,
        truth_rel_error_pct=round(compare["rel_error_pct"], 4),
        strata_detail=[
            {
                "code": item["code"],
                "label": item["label"],
                "population": item["population"],
                "sample_size": item["sample_size"],
                "sample_mean": round(item["sample_mean"], 4),
                "contribution": round(item["contribution"], 4),
                "ci_half": round(item["ci_half"], 4),
                "contribution_share_pct": item["contribution_share_pct"],
                "variance_share_pct": item["variance_share_pct"],
                "ci_half_pct": item["ci_half_pct"],
                "fpc": item["fpc"],
                "verified": True,
                "topped_up": next((int(a["added"]) for a in applied if a["code"] == item["code"]), 0),
            }
            for item in estimate["strata"]
        ],
        sample_ms=round(sample_ms, 2),
        truth_ms=base.truth_ms,
        full_scan_baseline_ms=int(dataset.full_scan_baseline_ms),
        status=QueryStatus.COMPLETED.value,
        run_by=actor["email"],
    )
    revision.created_at = datetime.utcnow()
    db.add(revision)
    db.flush()

    # 旧版本冻结为「已替代」，整行保留（页面/自检/导出仍可查看，但不再是最新）
    base.is_latest = False
    base.superseded_by_id = revision.id
    base.status = QueryStatus.SUPERSEDED.value
    # 旧版本未完成的复核链一并冻结
    old_qc = db.scalar(select(QcCheck).where(QcCheck.query_id == base.id))
    if old_qc is not None and old_qc.review_state != ReviewState.CONFIRMED.value:
        old_qc.review_state = ReviewState.SUPERSEDED.value

    # 新版本重跑自检（结论以新版本重算结果为准），复核链重置为待签
    new_qc = qc_service.run_check(db, revision.id, None, actor, None)
    db.flush()
    return revision, new_qc, applied


def request_topup(
    db: Session,
    query_id: int,
    actor: dict,
    ip: str | None = None,
) -> tuple[SampleTopup, dict]:
    """补样入口：规划 → 容量闸门 → 取未用样本 → 新版本 → 重算 + 重跑自检。

    返回 (补样单, 动作说明)。同一幂等键的重复调用不新增样本或结果。
    """
    query = db.get(ApproxQuery, query_id)
    if query is None:
        raise AppError("NOT_FOUND", 404, detail=f"query {query_id}")
    qc = db.scalar(select(QcCheck).where(QcCheck.query_id == query.id))
    if qc is None:
        raise AppError("QC_NOT_PASS", 409, detail="先跑精度自检，确认未达标后才能补样")
    if not query.is_latest:
        raise AppError("REVISION_SUPERSEDED", 409, detail="该版本已被替代，请对最新版本操作")
    if qc.verdict == "pass":
        raise AppError("TOPUP_NOT_NEEDED", 409, detail="自检已达标")

    dataset = query.dataset
    min_required = max((int(row.min_sample) for row in dataset.strata), default=30)
    contexts = _build_contexts(query, qc, min_required)
    decision = plan_stratum_topups(contexts, float(query.rel_error_pct), float(qc.target_pct))
    plan_rows = decision["plan"]
    key = idempotency_key_for(query.id, plan_rows)

    existing = db.scalar(select(SampleTopup).where(SampleTopup.idempotency_key == key))
    if existing is not None:
        # 幂等回放：done/rejected 直接返回既有结论；running 续跑（中断恢复）
        if existing.status == TopupStatus.DONE.value:
            return existing, {"action": "replayed", "message": "同一补样请求已完成，未新增样本"}
        if existing.status == TopupStatus.REJECTED.value:
            return existing, {"action": "replayed", "message": "同一补样请求此前因容量不足被拒绝"}
        return _resume_topup(db, existing, actor, ip)

    topup = SampleTopup(
        query_id=query.id,
        idempotency_key=key,
        status=TopupStatus.RUNNING.value,
        plan=plan_rows,
        applied=[],
        attempt_count=1,
        created_by=actor["email"],
    )
    db.add(topup)
    db.flush()

    if not decision["feasible"]:
        topup.status = TopupStatus.REJECTED.value
        lacking = [f"{r['code']}(需再补{r['add']}，未用仅{r['available_unused']})" for r in plan_rows if not r["feasible"]]
        topup.reject_reason = "未用样本容量不足：" + "、".join(lacking)
        audit_service.record(
            db,
            actor_email=actor["email"],
            actor_role=actor["role"],
            action="qc.topup.reject",
            entity="sample_topup",
            entity_id=str(topup.id),
            detail={"query": query.code, "reason": topup.reject_reason},
            ip=ip,
        )
        db.flush()
        return topup, {"action": "rejected", "message": topup.reject_reason}

    revision, _new_qc, applied = _create_revision(db, query, plan_rows, actor)
    topup.status = TopupStatus.DONE.value
    topup.new_query_id = revision.id
    topup.applied = applied
    audit_service.record(
        db,
        actor_email=actor["email"],
        actor_role=actor["role"],
        action="qc.topup",
        entity="sample_topup",
        entity_id=str(topup.id),
        detail={
            "base_query": query.code,
            "new_query": revision.code,
            "revision_no": revision.revision_no,
            "added": {a["code"]: a["added"] for a in applied},
            "new_sample_size": revision.sample_size,
            "new_ci_pct": float(revision.rel_error_pct),
        },
        ip=ip,
    )
    db.flush()
    return topup, {"action": "done", "message": "补样完成，已生成新版本并重算点估计/CI、重跑自检"}


def _resume_topup(db: Session, topup: SampleTopup, actor: dict, ip: str | None) -> tuple[SampleTopup, dict]:
    """续跑中断的 running 补样单：规划结论已固化在 topup.plan，按其继续执行。"""
    base = db.get(ApproxQuery, topup.query_id)
    topup.attempt_count = int(topup.attempt_count or 0) + 1
    plan_rows = list(topup.plan or [])
    if any(not row.get("feasible", True) for row in plan_rows):
        topup.status = TopupStatus.REJECTED.value
        topup.reject_reason = topup.reject_reason or "未用样本容量不足"
        db.flush()
        return topup, {"action": "rejected", "message": topup.reject_reason}
    revision, _new_qc, applied = _create_revision(db, base, plan_rows, actor)
    topup.status = TopupStatus.DONE.value
    topup.new_query_id = revision.id
    topup.applied = applied
    audit_service.record(
        db,
        actor_email=actor["email"],
        actor_role=actor["role"],
        action="qc.topup.resume",
        entity="sample_topup",
        entity_id=str(topup.id),
        detail={"base_query": base.code, "new_query": revision.code, "attempt": topup.attempt_count},
        ip=ip,
    )
    db.flush()
    return topup, {"action": "resumed", "message": "检测到中断的补样单，已续跑完成"}


def topup_out(db: Session, topup: SampleTopup, action: dict | None = None) -> dict:
    from src.constants.enums import TOPUP_STATUS_LABELS
    from src.services.query_service import query_out
    from src.utils.timeutil import local_iso

    base = db.get(ApproxQuery, topup.query_id)
    payload = {
        "id": topup.id,
        "query_id": topup.query_id,
        "query_code": base.code if base else None,
        "new_query_id": topup.new_query_id,
        "new_query": query_out(db, db.get(ApproxQuery, topup.new_query_id)) if topup.new_query_id else None,
        "idempotency_key": topup.idempotency_key,
        "status": topup.status,
        "status_label": TOPUP_STATUS_LABELS.get(topup.status, topup.status),
        "plan": list(topup.plan or []),
        "applied": list(topup.applied or []),
        "reject_reason": topup.reject_reason,
        "attempt_count": topup.attempt_count,
        "created_by": topup.created_by,
        "created_at": local_iso(topup.created_at),
    }
    if action:
        payload["action"] = action.get("action")
        payload["message"] = action.get("message")
    return payload
