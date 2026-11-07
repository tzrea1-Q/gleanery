import { create } from "zustand";

export const useComposer = create<{
  setText: ((text: string) => void) | null;
  register: (setText: ((text: string) => void) | null) => void;
  prefill: (text: string) => void;
}>((set, get) => ({
  setText: null,
  register: (setText) => set({ setText }),
  prefill: (text) => get().setText?.(text),
}));
