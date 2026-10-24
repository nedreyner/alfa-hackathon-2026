import { create } from 'zustand';

interface UiState {
  bannerDismissed: Record<string, boolean>;
  dismiss: (key: string) => void;
}

/** Небольшой UI-стор: копия сессии живёт в react-query (['session']), здесь — флаги баннеров. */
export const useUiStore = create<UiState>((set) => ({
  bannerDismissed: {},
  dismiss: (key) => set((s) => ({ bannerDismissed: { ...s.bannerDismissed, [key]: true } })),
}));
