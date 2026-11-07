import { useAppState, useModelConfigs, useSetCurrentModel } from "@/api/queries";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
      <Select
        value={current ? `${current.config_id}:${current.model}` : ""}
        onValueChange={(value) => {
          if (value === "manage") {
            open("models");
            return;
          }
          const split = value.indexOf(":");
          set.mutate({ config_id: Number(value.slice(0, split)), model: value.slice(split + 1) });
        }}
      >
        <SelectTrigger
          id="model-selector"
          size="sm"
          className="h-7 max-w-48 rounded-full border-0 bg-muted shadow-none dark:bg-muted"
        >
          <SelectValue placeholder="选择模型" />
        </SelectTrigger>
        <SelectContent>
          {configs.data
            ?.filter((c) => c.status === "ok")
            .map((c) => (
              <SelectGroup key={c.id}>
                <SelectLabel>{c.name}</SelectLabel>
                {c.favorites
                  .filter((f) => f.tool_test === "ok")
                  .map((f) => (
                    <SelectItem key={f.name} value={`${c.id}:${f.name}`}>
                      {c.model_labels?.[f.name] ?? f.name}
                    </SelectItem>
                  ))}
              </SelectGroup>
            ))}
          <SelectSeparator />
          <SelectItem value="manage">管理模型…</SelectItem>
        </SelectContent>
      </Select>
      {current?.kind === "chatgpt_plan" && (
        <span className="text-xs text-muted-foreground">
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
