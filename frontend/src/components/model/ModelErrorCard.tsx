import { useAppState, useModelConfigs, useSetCurrentModel } from "@/api/queries";
import { useUiStore } from "@/stores/ui";

export function ModelErrorCard({ error, reload }: { error: unknown; reload: () => void }) {
  const configs = useModelConfigs();
  const state = useAppState();
  const set = useSetCurrentModel();
  const open = useUiStore((s) => s.openSettings);
  let parsed: { code?: string; message?: string; hint?: string | null } = {};
  const raw =
    typeof error === "string"
      ? error
      : error instanceof Error
        ? error.message
        : JSON.stringify(error ?? "模型请求失败");
  try {
    parsed = JSON.parse(raw) as typeof parsed;
    if (parsed && typeof parsed.message === "string") {
      try {
        parsed = JSON.parse(parsed.message) as typeof parsed;
      } catch {
        /* 原始错误信息 */
      }
    }
  } catch {
    parsed = { message: raw };
  }
  parsed = parsed && typeof parsed === "object" ? parsed : { message: raw };
  const other = configs.data?.flatMap((c) =>
    c.status === "ok"
      ? c.favorites
          .filter(
            (f) =>
              f.tool_test === "ok" &&
              (parsed.code !== "MODEL_QUOTA_EXCEEDED" ||
                c.id !== state.data?.current_model?.config_id) &&
              (c.id !== state.data?.current_model?.config_id ||
                f.name !== state.data?.current_model?.model),
          )
          .map((f) => ({ id: c.id, config: c.name, model: f.name }))
      : [],
  )[0];
  const code = parsed.code ?? "MODEL_ERROR";
  const changeModel = [
    "MODEL_RECONNECT_REQUIRED",
    "MODEL_NOT_ELIGIBLE",
    "MODEL_UNSUPPORTED",
    "MODEL_AUTH_FAILED",
  ].includes(code);
  return (
    <div role="alert" className="mt-2 space-y-2 rounded border border-destructive p-3">
      <p>{code === "NO_MODEL" ? "先选一个模型" : parsed.message || raw}</p>
      {parsed.hint && <p>{parsed.hint}</p>}
      <div className="flex flex-wrap gap-2">
        {["MODEL_AUTH_FAILED", "MODEL_UNSUPPORTED", "NO_MODEL"].includes(code) && (
          <button className="rounded border p-2" onClick={() => open("models")}>
            去设置
          </button>
        )}
        {changeModel && (
          <button className="rounded border p-2" onClick={() => open("models")}>
            换个模型
          </button>
        )}
        {code === "MODEL_RECONNECT_REQUIRED" && (
          <a
            className="rounded border p-2"
            href="/api/chatgpt/connect"
            target="_blank"
            rel="noopener"
          >
            重新连接
          </a>
        )}
        {code === "MODEL_QUOTA_EXCEEDED" && (
          <a
            className="rounded border p-2"
            href="https://chatgpt.com/settings/usage"
            target="_blank"
            rel="noopener"
          >
            Manage usage
          </a>
        )}
        {![
          "MODEL_AUTH_FAILED",
          "MODEL_UNSUPPORTED",
          "MODEL_NOT_ELIGIBLE",
          "MODEL_QUOTA_EXCEEDED",
          "NO_MODEL",
        ].includes(code) && (
          <button
            className="rounded border p-2"
            onClick={reload}
            disabled={
              code === "MODEL_RECONNECT_REQUIRED" && state.data?.current_model?.status !== "ok"
            }
          >
            重试
          </button>
        )}
        {(code === "MODEL_RATE_LIMITED" || code === "MODEL_QUOTA_EXCEEDED") &&
          state.data &&
          other && (
            <button
              className="rounded border p-2"
              disabled={set.isPending}
              onClick={() =>
                set.mutate({ config_id: other.id, model: other.model }, { onSuccess: reload })
              }
            >
              换成 {other.config}
              {code === "MODEL_RATE_LIMITED" && `·${other.model}`} 并重试
            </button>
          )}
      </div>
      {set.isError && <p>切换模型失败，请重试</p>}
    </div>
  );
}
