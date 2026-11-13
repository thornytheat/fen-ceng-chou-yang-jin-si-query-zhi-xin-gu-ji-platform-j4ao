import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../hooks/useStore';
import { useAsync } from '../hooks/useAsync';
import { useToast } from '../hooks/useToast';
import { authStore } from '../stores/authStore';
import { qcStore } from '../stores/qcStore';
import { queryStore } from '../stores/queryStore';
import { queryApi } from '../api/queries';
import { SIGNOFF_STAGES } from '../constants/enums';
import { can } from '../constants/roles';
import { errorMessage } from '../utils/errorMessage';
import VerdictPill from '../components/common/VerdictPill';
import RulerBar from '../components/common/RulerBar';
import StatTile from '../components/common/StatTile';
import EmptyState from '../components/common/EmptyState';
import VialTag from '../components/common/VialTag';
import { formatInt, formatMetric, formatPct } from '../utils/format';

const STAGE_ROLE: Record<string, string> = {
  analyst: 'analyst',
  admin: 'admin',
  viewer: 'viewer',
};

export default function Qc() {
  const auth = useStore(authStore);
  const queries = useStore(queryStore);
  const state = useStore(qcStore);
  const toast = useToast();
  const role = auth.user?.role;

  const [queryId, setQueryId] = useState<number | null>(null);

  useEffect(() => {
    void queryStore.load().catch(() => undefined);
    void qcStore.load().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (queryId === null && queries.items.length) {
      setQueryId(queries.items[0].id);
    }
  }, [queries.items, queryId]);

  const query = useMemo(() => queries.items.find((item) => item.id === queryId) ?? null, [queries.items, queryId]);
  const selected = state.selected;
  const target = selected?.target_pct ?? 2;
  const unitScale = selected?.unit === '元' ? 100 : 10;

  const run = useAsync(async () => {
    if (!queryId) return null;
    const qc = await qcStore.run(queryId);
    toast.ok(`自检完成：${qc.verdict_label}（相对误差 ${qc.rel_error_pct.toFixed(2)}% / CI ±${qc.ci_pct.toFixed(2)}%）`);
    return qc;
  });

  const topup = useAsync(async () => {
    if (!selected) return null;
    try {
      const result = await qcStore.topup(selected.query_id);
      if (result.status === 'rejected') {
        toast.error(result.reject_reason ?? '未用样本容量不足，补样已拒绝（未产生新样本）');
      } else {
        toast.ok(result.message ?? '补样完成：已生成新版本，点估计/CI 已重算、自检已重跑');
        await Promise.all([qcStore.load(), queryStore.load()]);
        const newest = qcStore.getState().items.find((item) => item.query_id === result.new_query_id);
        if (newest) qcStore.select(newest);
      }
      return result;
    } catch (error) {
      toast.error(errorMessage(error));
      throw error;
    }
  });

  const sign = useAsync(async (stage: string) => {
    if (!selected) return null;
    const allowed = can(role, 'qc:signoff') || (can(role, 'qc:acknowledge') && stage === 'viewer');
    if (!allowed) {
      toast.error('当前角色不能签这一步（服务端会 403）');
      return null;
    }
    const qc = await qcStore.signoff(selected.id, {
      stage,
      decision: 'approve',
      note: stage === 'viewer' ? '业务方已知悉本次估算的误差范围' : '按精度标准复核通过',
    });
    toast.ok(`已记录 ${stage} 签署，当前状态：${qc.review_state_label}`);
    return qc;
  });

  const exportMd = useAsync(async (id: number) => {
    try {
      const markdown = await queryApi.exportMarkdown(id);
      const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `sampleaqp-estimate-${id}.md`;
      anchor.click();
      URL.revokeObjectURL(url);
      toast.ok('估算说明 Markdown 已导出');
      return markdown;
    } catch (error) {
      toast.error(errorMessage(error));
      throw error;
    }
  });

  const stageState = (stage: string) => {
    const signed = (selected?.signoffs ?? []).find((item) => item.stage === stage && item.decision === 'approve');
    if (signed) return 'done';
    if (selected?.next_stage === stage) return 'next';
    return 'todo';
  };

  const linkedQuery = useMemo(
    () => queries.items.find((item) => item.id === selected?.query_id) ?? null,
    [queries.items, selected],
  );
  const chain = linkedQuery?.revision_chain ?? [];
  const canTopup =
    !!selected &&
    selected.verdict === 'fail' &&
    selected.is_latest &&
    selected.review_state !== 'superseded' &&
    can(role, 'qc:topup');
  const chainFrozen = selected?.review_state === 'superseded' || selected?.is_latest === false;
  const lastTopup = state.topups.find((item) => item.query_id === selected?.query_id);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">PRECISION QC · 抽样 vs 全量</div>
          <h2>误差说不清，就别拿去上会</h2>
          <p className="page-lead">
            自检把点估计与全量真值、CI 半宽与精度标准、每层样本量与 30 行下限一起判；
            通过后按「分析师提交 → 负责人复核 → 业务方知悉」三步签署，才能导出正式说明。
          </p>
        </div>
        <div className="page-head-meta mono">
          <span>{state.items.length} QC RECORDS</span>
          <span>{state.items.filter((item) => item.verdict === 'pass').length} PASS</span>
        </div>
      </header>

      <div className="qc-layout">
        <section className="panel qc-console">
          <div className="panel-head">
            <h3>选择查询</h3>
            <VialTag code="QC" label="精度自检" />
          </div>
          <label className="field">
            <span>本次要自检的查询</span>
            <select className="input" value={queryId ?? ''} onChange={(event) => setQueryId(Number(event.target.value))}>
              {queries.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.code} · {item.metric_label} · ±{item.rel_error_pct.toFixed(2)}%
                </option>
              ))}
              {!queries.items.length ? <option value="">还没有查询记录</option> : null}
            </select>
          </label>

          {query ? (
            <div className="console-readout stack mono">
              <div>
                <span>点估计</span>
                <b>{formatMetric(query.value_estimate, query.unit, 100)}</b>
              </div>
              <div>
                <span>真值</span>
                <b>{formatMetric(query.true_value, query.unit, 100)}</b>
              </div>
              <div>
                <span>CI</span>
                <b>±{query.rel_error_pct.toFixed(2)}%</b>
              </div>
            </div>
          ) : null}

          <button id="run-qc" className="btn btn-primary" disabled={!queryId || run.busy || !can(role, 'qc:run')} onClick={() => void run.run()}>
            {run.busy ? '正在比对 …' : '跑精度自检'}
          </button>
          {!can(role, 'qc:run') ? <div className="tiny muted">业务方只读；分析师/负责人可跑自检与签署前两步。</div> : null}
          {run.error ? <div className="form-error">{run.error}</div> : null}

          <div className="panel-head qc-list-head">
            <h3>自检记录</h3>
            <span className="tiny mono">{state.items.length}</span>
          </div>
          <div className="qc-list">
            {state.items.map((item) => (
              <button
                key={item.id}
                className={`qc-card ${selected?.id === item.id ? 'is-active' : ''} ${!item.is_latest ? 'is-superseded' : ''}`}
                onClick={() => qcStore.select(item)}
              >
                <div className="qc-card-top">
                  <span className="mono">
                    {item.code}
                    <em className="revision-tag"> v{item.revision_no}{item.is_latest ? '' : ' · 已替代'}</em>
                  </span>
                  <VerdictPill verdict={item.verdict} label={item.verdict_label} size="sm" />
                </div>
                <div className="qc-card-meta mono">
                  误差 {item.rel_error_pct.toFixed(2)}% · CI ±{item.ci_pct.toFixed(2)}%
                </div>
                <div className="tiny muted">
                  {item.review_state_label} · {item.created_by}
                </div>
              </button>
            ))}
            {!state.items.length ? <div className="tiny muted">还没有自检记录，选一条查询跑一次。</div> : null}
          </div>
        </section>

        <section className="panel qc-detail">
          {selected ? (
            <>
              <div className="panel-head">
                <div>
                  <div className="eyebrow">
                    {selected.code} · {selected.query_code}
                  </div>
                  <h3>{selected.dataset_name} · {selected.metric_label}</h3>
                </div>
                <div className="panel-actions">
                  <VerdictPill verdict={selected.verdict} label={selected.verdict_label} />
                  <button
                    className="btn btn-sm"
                    disabled={exportMd.busy || !selected.exportable}
                    title={selected.exportable ? '' : '仅最新且三签复核通过的版本可导出'}
                    onClick={() => void exportMd.run(selected.query_id)}
                  >
                    导出估算说明
                  </button>
                </div>
              </div>

              {chain.length > 1 ? (
                <div className="revision-chain" data-testid="revision-chain">
                  <span className="tiny muted">版本替代关系（旧版只读保留，仅最新版可导出）：</span>
                  <div className="revision-steps">
                    {chain.map((item) => (
                      <span
                        key={item.id}
                        className={`revision-chip ${item.is_latest ? 'is-latest' : ''} ${item.status === 'superseded' ? 'is-superseded' : ''}`}
                      >
                        <b className="mono">v{item.revision_no}</b>
                        <span className="mono tiny">{item.code}</span>
                        <span className="tiny">n={formatInt(item.sample_size)} · ±{item.rel_error_pct.toFixed(2)}%</span>
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="stat-grid three">
                <StatTile label="点估计" value={formatMetric(selected.value_estimate, selected.unit, unitScale)} hint={`样本 ${formatInt(selected.sample_size)} 行`} tone="brass" />
                <StatTile label="全量真值" value={formatMetric(selected.true_value, selected.unit, unitScale)} hint="同口径全表聚合" tone="steel" />
                <StatTile
                  label="自检结论"
                  value={selected.verdict_label}
                  hint={`标准 ≤ ${selected.target_pct.toFixed(2)}%`}
                  tone={selected.verdict === 'pass' ? 'pass' : 'fail'}
                />
              </div>

              <div className="qc-rulers">
                <RulerBar value={selected.rel_error_pct} target={selected.target_pct} caption="点估计相对误差 vs 精度标准" />
                <RulerBar value={selected.ci_pct} target={selected.target_pct} caption="95% CI 半宽 vs 精度标准" />
              </div>

              {selected.verdict === 'fail' ? (
                <div className="topup-panel" data-testid="topup-panel">
                  <div className="topup-head">
                    <b>未达标处置：只给未达标层补未用样本（不重建方案、不作废已抽层）</b>
                    {chainFrozen ? (
                      <span className="tiny muted">该版本已被新版本替代，复核链冻结，请在最新版本上操作。</span>
                    ) : (
                      <button
                        id="run-topup"
                        className="btn btn-primary btn-sm"
                        disabled={!canTopup || topup.busy}
                        title={canTopup ? '' : '仅分析师/负责人可对最新未达标版本补样'}
                        onClick={() => void topup.run()}
                      >
                        {topup.busy ? '补样并重算 …' : '对未达标层补样'}
                      </button>
                    )}
                  </div>
                  {!can(role, 'qc:topup') && !chainFrozen ? (
                    <div className="tiny muted">业务方只读；补样由分析师发起、负责人同样可发起。容量不足时后端直接拒绝，不产生新样本。</div>
                  ) : null}
                  {topup.error ? <div className="form-error">{topup.error}</div> : null}
                  {lastTopup ? (
                    <div className={`topup-result is-${lastTopup.status}`}>
                      <div className="tiny mono">
                        补样单 #{lastTopup.id} · {lastTopup.status_label} · 第 {lastTopup.attempt_count} 次执行
                        （幂等键 {lastTopup.idempotency_key.slice(0, 18)}…）
                      </div>
                      {lastTopup.reject_reason ? <div className="form-error">{lastTopup.reject_reason}</div> : null}
                      <div className="topup-plan">
                        {lastTopup.plan.map((row) => (
                          <div key={row.code} className={`topup-row ${row.failed ? 'is-failed' : ''} ${!row.feasible ? 'is-infeasible' : ''}`}>
                            <b>{row.label}</b>
                            <span className="mono tiny">
                              已抽 {row.had} → 目标 {row.target}（补 +{row.add}）· 未用余量 {row.available_unused}
                            </span>
                            <span className="tiny muted">{row.reason}</span>
                          </div>
                        ))}
                      </div>
                      {lastTopup.new_query ? (
                        <div className="tiny ok">
                          已生成新版本 {lastTopup.new_query.code}（v{lastTopup.new_query.revision_no}）：样本{' '}
                          {formatInt(lastTopup.new_query.sample_size)} 行，CI ±{lastTopup.new_query.rel_error_pct.toFixed(2)}%，
                          请在左侧自检记录选择新版本继续三级复核。
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}

              <h4 className="section-title">检查项</h4>
              <div className="check-list">
                {selected.checks.map((item) => (
                  <div key={item.code} className={`check-row ${item.ok ? 'is-ok' : 'is-bad'}`}>
                    <span className="check-flag">
                      {item.code === 'sampling_coverage' ? 'REF' : item.ok ? 'PASS' : 'FAIL'}
                    </span>
                    <div className="check-copy">
                      <b>{item.label}</b>
                      <span className="tiny muted">{item.note}</span>
                    </div>
                    <div className="check-values mono">
                      <b>{item.actual}</b>
                      <span>{item.threshold}</span>
                    </div>
                  </div>
                ))}
              </div>

              <h4 className="section-title">三角色复核链</h4>
              <div className="signoff-chain">
                {SIGNOFF_STAGES.map((stage, index) => {
                  const stateOf = stageState(stage.value);
                  const signed = (selected.signoffs ?? []).find((item) => item.stage === stage.value);
                  const canSign = !chainFrozen && stateOf === 'next' && role === STAGE_ROLE[stage.value];
                  return (
                    <div key={stage.value} className={`signoff-step is-${stateOf}${chainFrozen ? ' is-frozen' : ''}`}>
                      <div className="signoff-index mono">{String(index + 1).padStart(2, '0')}</div>
                      <div className="signoff-copy">
                        <b>{stage.label}</b>
                        <span className="tiny muted">
                          需要角色：{stage.role === 'analyst' ? '分析师' : stage.role === 'admin' ? '分析负责人' : '业务方'}
                        </span>
                        {signed ? (
                          <span className="tiny mono signed-line">
                            {signed.actor_email} · {signed.at} · {signed.decision === 'approve' ? '通过' : '驳回'}
                          </span>
                        ) : null}
                      </div>
                      <div className="signoff-action">
                        {chainFrozen ? (
                          <span className="signoff-done mono">FROZEN</span>
                        ) : stateOf === 'done' ? (
                          <span className="signoff-done mono">SIGNED</span>
                        ) : (
                          <button
                            id={`sign-${stage.value}`}
                            className="btn btn-sm"
                            disabled={!canSign || sign.busy}
                            title={canSign ? '' : '当前角色不能签这一步（服务端会 403）'}
                            onClick={() => void sign.run(stage.value)}
                          >
                            {sign.busy ? '签署中 …' : '签署'}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="tiny muted">
                版本 v{selected.revision_no}（{selected.is_latest ? '最新' : '已被替代'}）· 覆盖 {formatPct(selected.coverage_pct, 4)} · 最小层样本{' '}
                {selected.min_stratum_sample} 行 · 复核状态：{selected.review_state_label}
                {selected.verdict === 'fail' && selected.is_latest
                  ? ' · 结论未达标：对未达标层补样后自动重算并生成新版本，再走三级复核'
                  : ''}
                {!selected.exportable ? ' · 仅最新且三签通过版本可导出' : ''}
              </div>
              {sign.error ? <div className="form-error">{sign.error}</div> : null}
            </>
          ) : (
            <EmptyState
              title="还没有自检结果"
              hint="先在左侧选一条查询并跑自检；没有查询时先去「近似查询」页跑一次。"
            />
          )}
        </section>
      </div>
    </div>
  );
}
