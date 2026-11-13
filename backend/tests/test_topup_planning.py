"""补样纯函数单测：只补未达标层、容量闸门、幂等键稳定性。

不依赖 DB / 第三方包，直接覆盖 topup_service 的纯函数规划层，
对应需求：未达标层从原数据补未用样本、容量仍不足就拒绝、重跑同请求不新增样本。
"""
from __future__ import annotations

import pytest

from src.services.topup_planning import (
    StratumTopupContext,
    idempotency_key_for,
    plan_stratum_topups,
)


def ctx(code: str, population: int, had: int, failed: bool, ci_pct: float = 1.0, min_required: int = 30) -> StratumTopupContext:
    return StratumTopupContext(
        code=code,
        label=code,
        population=population,
        had=had,
        min_required=min_required,
        ci_half_pct=ci_pct,
        failed=failed,
    )


def test_passing_strata_are_kept_untouched() -> None:
    """已达标层 add=0，已抽好的样本不作废、不重建。"""
    result = plan_stratum_topups(
        [ctx("A", 1000, 120, failed=False), ctx("B", 800, 60, failed=False)],
        global_ci_pct=1.5,
        target_pct=2.0,
    )
    assert result["feasible"] is True
    assert result["total_add"] == 0
    assert all(row["add"] == 0 for row in result["plan"])
    assert all(row["reason"] == "已达标，保留已抽样本" for row in result["plan"])


def test_only_failed_strata_get_topup_and_others_kept() -> None:
    """最小样本不达标的层补到 30，其余层原样保留。"""
    result = plan_stratum_topups(
        [ctx("A", 1000, 120, failed=False), ctx("B", 800, 12, failed=True, min_required=30)],
        global_ci_pct=1.5,
        target_pct=2.0,
    )
    by_code = {row["code"]: row for row in result["plan"]}
    assert by_code["A"]["add"] == 0
    assert by_code["B"]["target"] == 30
    assert by_code["B"]["add"] == 18
    assert by_code["B"]["available_unused"] == 800 - 12
    assert result["total_add"] == 18
    assert result["feasible"] is True


def test_ci_failure_scales_target_by_overrun_ratio() -> None:
    """CI 超标层按 (实测/目标)² 放大样本量，且不超过层容量。"""
    # global 4% vs target 2% → scale=4，had=50 → target=200
    result = plan_stratum_topups(
        [ctx("BIG", 1000, 50, failed=True, ci_pct=3.0)],
        global_ci_pct=4.0,
        target_pct=2.0,
    )
    row = result["plan"][0]
    assert row["target"] == 200
    assert row["add"] == 150
    assert row["feasible"] is True

    # 放大后超过层容量时夹到 N_h，未用余量 = N_h - had 恰好够则仍可行
    capped = plan_stratum_topups(
        [ctx("TINY", 120, 50, failed=True, ci_pct=3.0)],
        global_ci_pct=4.0,
        target_pct=2.0,
    )["plan"][0]
    assert capped["target"] == 120
    assert capped["add"] == 70
    assert capped["available_unused"] == 70
    assert capped["feasible"] is True


def test_insufficient_unused_capacity_is_rejected_before_any_sample() -> None:
    """未用样本不足以补足差额 → feasible=False，上层必须拒绝且不写新样本。"""
    result = plan_stratum_topups(
        [
            ctx("OK", 1000, 100, failed=False),
            ctx("STARVED", 40, 10, failed=True, min_required=30),  # 需再补 20，未用仅 30 → 够
        ],
        global_ci_pct=1.5,
        target_pct=2.0,
    )
    assert result["feasible"] is True

    rejected = plan_stratum_topups(
        [ctx("STARVED", 20, 10, failed=True, min_required=30)],  # 需再补 20，未用仅 10
        global_ci_pct=1.5,
        target_pct=2.0,
    )
    assert rejected["feasible"] is False
    row = rejected["plan"][0]
    assert row["add"] == 20
    assert row["available_unused"] == 10
    assert row["feasible"] is False
    assert "容量不足" in row["reason"]


def test_idempotency_key_is_stable_for_same_request() -> None:
    """同一查询版本 + 同一补样决策 → 同一幂等键；不同目标 → 不同键。"""
    plan_a = [
        {"code": "A", "had": 100, "target": 100},
        {"code": "B", "had": 12, "target": 30},
    ]
    plan_b = [dict(row) for row in plan_a]
    plan_c = [
        {"code": "A", "had": 100, "target": 100},
        {"code": "B", "had": 12, "target": 45},
    ]
    key1 = idempotency_key_for(7, plan_a)
    key2 = idempotency_key_for(7, plan_b)
    key3 = idempotency_key_for(7, plan_c)
    key4 = idempotency_key_for(8, plan_a)
    assert key1 == key2
    assert key1 != key3
    assert key1 != key4
    assert key1.startswith("topup:q7:")


def test_target_never_below_current_sample_size() -> None:
    """目标样本量不得低于已抽量，避免出现负补样。"""
    result = plan_stratum_topups(
        [ctx("A", 1000, 200, failed=True, ci_pct=0.5)],
        global_ci_pct=1.0,
        target_pct=2.0,
    )
    row = result["plan"][0]
    assert row["target"] >= 200
    assert row["add"] == 0
