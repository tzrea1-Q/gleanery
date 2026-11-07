import { useAppState, useModelConfigs, useSetCurrentModel } from "@/api/queries";
import { useUiStore } from "@/stores/ui";

export function ModelSelector() {
  const configs = useModelConfigs();
  const state = useAppState();
  const set = useSetCurrentModel();
  const open = useUiStore((s) => s.openSettings);
  const current = state.data?.current_model;
  return (
    <div className="flex items-center gap-2">
      <label className="sr-only" htmlFor="model-selector">
        当前模型
      </label>
      <select
        id="model-selector"
        className="max-w-48 rounded border p-1 text-sm"
        value={current ? `${current.config_id}:${current.model}` : ""}
        onChange={(e) => {
          if (e.target.value === "manage") {
            open("models");
            return;
          }
          const option = e.target.selectedOptions[0];
          if (option?.dataset.id && option.dataset.model)
            set.mutate({ config_id: Number(option.dataset.id), model: option.dataset.model });
        }}
      >
        {!current && <option value="">选择模型</option>}
        {configs.data
          ?.filter((c) => c.status === "ok")
          .map((c) => (
            <optgroup key={c.id} label={c.name}>
              {c.favorites
                .filter((f) => f.tool_test === "ok")
                .map((f) => (
                  <option
                    key={f.name}
                    value={`${c.id}:${f.name}`}
                    data-id={c.id}
                    data-model={f.name}
                  >
                    {current?.config_id === c.id && current.model === f.name ? "✓ " : ""}
                    {c.model_labels?.[f.name] ?? f.name}
                  </option>
                ))}
            </optgroup>
          ))}
        <option value="manage">管理模型…</option>
      </select>
      {current?.kind === "chatgpt_plan" && (
        <span className="text-sm">
          Using ChatGPT plan ·{" "}
          <a
            href="https://chatgpt.com/settings/usage"
            target="_blank"
            rel="noopener"
            className="underline"
          >
            Manage usage
          </a>
        </span>
      )}
      {set.isError && <span role="alert">切换失败</span>}
    </div>
  );
}
