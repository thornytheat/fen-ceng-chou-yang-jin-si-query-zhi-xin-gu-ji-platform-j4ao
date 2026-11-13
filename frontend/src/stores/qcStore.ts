/** 精度自检 store：检查项 + 三角色复核链 + 未达标层补样（版本化）。 */
import { qcApi, type SignoffPayload } from '../api/qc';
import type { QcCheck, SampleTopup } from '../types/models';
import { createStore } from './base';

export interface QcState {
  items: QcCheck[];
  selected: QcCheck | null;
  topups: SampleTopup[];
  loading: boolean;
  running: boolean;
  signing: boolean;
  topping: boolean;
  error: string | null;
}

const store = createStore<QcState>({
  items: [],
  selected: null,
  topups: [],
  loading: false,
  running: false,
  signing: false,
  topping: false,
  error: null,
});

async function load(): Promise<void> {
  store.set({ loading: true, error: null });
  try {
    const [result, topupResult] = await Promise.all([qcApi.list(), qcApi.topups().catch(() => ({ items: [], total: 0 }))]);
    store.set((state) => ({
      loading: false,
      items: result.items,
      topups: topupResult.items,
      selected: state.selected ?? result.items[0] ?? null,
    }));
  } catch (error) {
    store.set({ loading: false, error: '自检记录加载失败' });
    throw error;
  }
}

async function run(queryId: number): Promise<QcCheck> {
  store.set({ running: true, error: null });
  try {
    const qc = await qcApi.run({ query_id: queryId });
    store.set((state) => ({
      running: false,
      items: [qc, ...state.items.filter((item) => item.id !== qc.id)],
      selected: qc,
    }));
    return qc;
  } catch (error) {
    store.set({ running: false });
    throw error;
  }
}

async function signoff(id: number, payload: SignoffPayload): Promise<QcCheck> {
  store.set({ signing: true });
  try {
    const result = await qcApi.signoff(id, payload);
    store.set((state) => ({
      signing: false,
      items: state.items.map((item) => (item.id === id ? result.qc : item)),
      selected: result.qc,
    }));
    return result.qc;
  } catch (error) {
    store.set({ signing: false });
    throw error;
  }
}

/** 对未达标版本发起补样；同一请求重放由后端幂等保证，不新增样本或结果。 */
async function topup(queryId: number): Promise<SampleTopup> {
  store.set({ topping: true, error: null });
  try {
    const result = await qcApi.topup(queryId);
    store.set((state) => ({
      topping: false,
      topups: [result, ...state.topups.filter((item) => item.id !== result.id)],
    }));
    return result;
  } catch (error) {
    store.set({ topping: false });
    throw error;
  }
}

function select(qc: QcCheck | null) {
  store.set({ selected: qc });
}

export const qcStore = {
  subscribe: store.subscribe,
  getState: store.getState,
  load,
  run,
  signoff,
  topup,
  select,
};
