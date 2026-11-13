const FALLBACK: Record<string, string> = {
  AUTH_MISSING: '请先登录再操作',
  AUTH_INVALID: '账号或密码不正确',
  FORBIDDEN: '当前角色没有该操作权限（服务端 403）',
  NOT_FOUND: '对象不存在或已被删除',
  VALIDATION: '请求参数不合法',
  RATE_LIMITED: '请求过于频繁，请稍后再试',
  PLAN_NOT_ACTIVE: '只有已审批的方案才能跑近似查询',
  QC_ORDER: '复核链必须按 分析师 → 负责人 → 业务方 顺序签署',
  QC_DUPLICATE_SIGNOFF: '该复核链已经签完',
  QC_NOT_PASS: '自检未达标：请先对未达标层补样后重跑自检',
  TOPUP_CAPACITY: '未用样本容量不足，无法补足未达标层，补样已拒绝',
  TOPUP_NOT_NEEDED: '该版本自检已达标，无需补样',
  TOPUP_BAD_STATE: '当前版本状态不允许补样（仅未达标版本可补样）',
  TOPUP_REJECTED: '该补样单因容量不足已被拒绝，未产生新样本',
  REVISION_SUPERSEDED: '该版本已被补样后的新版本替代，只读保留',
  EXPORT_NOT_READY: '只有最新且三签复核通过的版本才能导出',
  DATASET_EMPTY: '数据集还没有明细行',
  INTERNAL: '服务内部错误，请稍后重试',
};

export function errorMessage(payload: unknown, fallback = '操作失败'): string {
  if (!payload) return fallback;
  if (typeof payload === 'string') return payload;
  const value = payload as { code?: string; message?: string; detail?: unknown };
  if (value.code && FALLBACK[value.code]) return FALLBACK[value.code];
  if (value.message) return value.message;
  return fallback;
}
