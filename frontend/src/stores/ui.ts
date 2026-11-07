import { create } from "zustand";

type UiState = {
  settingsOpen: boolean;
  settingsTab: "models" | "collect" | "data";
  openSettings: (tab?: "models" | "collect" | "data") => void;
  closeSettings: () => void;
  sessionExpired: boolean;
};

export const useUiStore = create<UiState>((set) => ({
  settingsOpen: false,
  settingsTab: "models",
  openSettings: (tab = "models") => set({ settingsOpen: true, settingsTab: tab }),
  closeSettings: () => set({ settingsOpen: false }),
  sessionExpired: false,
}));
