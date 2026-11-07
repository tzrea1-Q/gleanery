import { create } from "zustand";

export type ConfirmOptions = {
  title: string;
  description?: string;
  confirmLabel?: string;
  destructive?: boolean;
};

type ConfirmState = {
  request: ConfirmOptions | null;
  resolve: ((confirmed: boolean) => void) | null;
};

export const useConfirmStore = create<ConfirmState>(() => ({ request: null, resolve: null }));

/** `window.confirm` 的异步替代，由 `ConfirmHost` 显示。 */
export function askConfirm(request: ConfirmOptions) {
  // 弹窗一次只显示一个，新请求顶掉旧请求时按取消处理。
  useConfirmStore.getState().resolve?.(false);
  return new Promise<boolean>((resolve) => useConfirmStore.setState({ request, resolve }));
}

export function settleConfirm(confirmed: boolean) {
  useConfirmStore.getState().resolve?.(confirmed);
  useConfirmStore.setState({ request: null, resolve: null });
}
