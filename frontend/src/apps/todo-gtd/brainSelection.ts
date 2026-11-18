// Account-local selection. Content views remount on generation, including a fallback.
import { useSyncExternalStore } from 'react';
export interface BrainSummary {
  id: number;
  name: string;
  folder: string;
  status: 'active' | 'archived';
}
let state: { account: number | null; id: number | null; brains: BrainSummary[]; generation: number; notice: string } = {
  account: null,
  id: null,
  brains: [],
  generation: 0,
  notice: '',
};
const listeners = new Set<() => void>();
function emit() {
  listeners.forEach((f) => f());
}
export function brainName(brain: BrainSummary) {
  return brain.name || `Brain ${state.brains.findIndex((b) => b.id === brain.id) + 1}`;
}
export function selectedBrain() {
  return state.id;
}
export function brainGeneration() {
  return state.generation;
}
export function useBrainSelection() {
  return useSyncExternalStore(
    (f) => {
      listeners.add(f);
      return () => {
        listeners.delete(f);
      };
    },
    () => state,
  );
}
export function selectBrain(id: number, notice = '') {
  if (!state.brains.some((b) => b.id === id && b.status === 'active')) return;
  state = { ...state, id, notice, generation: state.generation + 1 };
  try {
    localStorage.setItem(`brain:${state.account}`, String(id));
  } catch {
    /* Storage may be disabled. */
  }
  emit();
}
export function initializeBrains(account: number, brains: BrainSummary[]) {
  let id = state.account === account ? state.id : null;
  if (state.account !== account) {
    try {
      id = Number(localStorage.getItem(`brain:${account}`));
    } catch {
      /* Storage may be disabled. */
    }
    const query =
      typeof window === 'undefined' ? null : Number(new URLSearchParams(window.location.search).get('brain'));
    if (brains.some((b) => b.id === query && b.status === 'active')) id = query;
  }
  id =
    brains.find((b) => b.id === id && b.status === 'active')?.id ??
    brains.find((b) => b.status === 'active')?.id ??
    null;
  state = { ...state, account, brains, id, notice: '', generation: state.generation + 1 };
  try {
    if (id !== null) localStorage.setItem(`brain:${account}`, String(id));
  } catch {
    /* Storage may be disabled. */
  }
  emit();
}
export function refreshBrains(brains: BrainSummary[]) {
  state = { ...state, brains };
  if (!brains.some((b) => b.id === state.id && b.status === 'active')) {
    const first = brains.find((b) => b.status === 'active');
    if (first) {
      selectBrain(first.id, 'That brain is no longer available. Opened your first brain.');
      return;
    }
  }
  emit();
}
