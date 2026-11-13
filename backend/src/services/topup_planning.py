"""补样规划纯函数：零第三方依赖，可被单测直接覆盖。

口径：
  * 已达标且不缺最小样本的层 → add=0，已抽样本原样保留（不作废、不重建方案）；
  * 未达标层目标样本量 = max(最小样本要求, 按 CI 超标比例放大的量)，且不超过层容量；
  * 未用样本余量 = N_h - had；余量不足以补足差额 → feasible=False，上层据此拒绝补样。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass
class StratumTopupContext:
    """补样规划所需的单层上下文。"""
    code: str
    label: str
    population: int          # 层容量 N_h
    had: int                 # 该版本已抽样本数
    min_required: int        # 最小层样本要求（默认 30）
    ci_half_pct: float       # 该版本该层 CI 半宽占总点估计百分比
    failed: bool             # 本次自检该层是否未达标


def _scaled_target(ctx: StratumTopupContext, global_ci_pct: float, target_pct: float) -> int:
    """CI 超标的层按超标比例平方放大样本量（含 FPC 的一阶近似），并夹在层容量内。"""
    if global_ci_pct <= target_pct or global_ci_pct <= 0:
        return ctx.had
    scale = (global_ci_pct / target_pct) ** 2
    candidate = int(round(ctx.had * scale))
    return min(candidate, ctx.population)


def plan_stratum_topups(
    contexts: list[StratumTopupContext],
    global_ci_pct: float,
    target_pct: float,
) -> dict:
    """给出每层补样决策与整体可行性，不触碰数据库。"""
    plan_rows: list[dict] = []
    feasible = True
    total_add = 0
    for ctx in contexts:
        available = max(0, int(ctx.population) - int(ctx.had))
        target = max(int(ctx.had), int(ctx.min_required))
        if ctx.failed:
            target = max(target, _scaled_target(ctx, global_ci_pct, target_pct))
        add = max(0, target - int(ctx.had))
        layer_feasible = add <= available
        if not layer_feasible:
            feasible = False
        if add > 0:
            total_add += add
        if ctx.failed and not layer_feasible:
            reason = "未用样本容量不足，无法补足"
        elif ctx.failed:
            reason = "未达标层，补入未用样本"
        else:
            reason = "已达标，保留已抽样本"
        plan_rows.append(
            {
                "code": ctx.code,
                "label": ctx.label,
                "population": int(ctx.population),
                "had": int(ctx.had),
                "min_required": int(ctx.min_required),
                "target": int(target),
                "add": int(add),
                "available_unused": int(available),
                "failed": bool(ctx.failed),
                "feasible": bool(layer_feasible),
                "reason": reason,
            }
        )
    return {"feasible": feasible, "total_add": total_add, "plan": plan_rows}


def idempotency_key_for(query_id: int, plan_rows: list[dict]) -> str:
    """确定性幂等键：同一查询版本 + 同一组「层 → 目标样本量」决策永远得到同一个键。"""
    fingerprint = [{"code": row["code"], "target": row["target"], "had": row["had"]} for row in plan_rows]
    raw = json.dumps({"q": query_id, "p": fingerprint}, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"topup:q{query_id}:{digest}"
