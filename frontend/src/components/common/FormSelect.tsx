import type { ComponentProps, ReactNode } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Radix 的 SelectItem 不接受空字符串，而这里的"全部""新建数据集"都用空值表示。
const EMPTY = "__empty__";

export type FormSelectOption = { value: string; label: ReactNode; disabled?: boolean };

export function FormSelect({
  id,
  value,
  onValueChange,
  options,
  placeholder,
  disabled,
  size,
  className,
  "aria-label": ariaLabel,
}: {
  id?: string;
  value: string;
  onValueChange: (value: string) => void;
  options: FormSelectOption[];
  placeholder?: string;
  disabled?: boolean;
  size?: ComponentProps<typeof SelectTrigger>["size"];
  className?: string;
  "aria-label"?: string;
}) {
  return (
    <Select
      value={value === "" ? EMPTY : value}
      onValueChange={(next) => onValueChange(next === EMPTY ? "" : next)}
      disabled={disabled}
    >
      <SelectTrigger id={id} size={size} className={className ?? "w-full"} aria-label={ariaLabel}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem
            key={option.value}
            value={option.value === "" ? EMPTY : option.value}
            disabled={option.disabled}
          >
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
