import { useId, type ReactNode } from "react";
import { Slot } from "radix-ui";
import { Field, FieldContent, FieldDescription, FieldLabel } from "@/components/ui/field";
import { cn } from "@/lib/utils";

/** 标签加控件的一行。控件只放一个，`id` 由这里生成并传给它，标签才能关联上。 */
export function FormRow({
  label,
  description,
  stacked,
  className,
  children,
}: {
  label: ReactNode;
  description?: ReactNode;
  /** 标签放在控件上方。默认两列。 */
  stacked?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <Field
      orientation={stacked ? "vertical" : "horizontal"}
      className={cn(!stacked && "grid grid-cols-[6rem_minmax(0,1fr)] items-start gap-2", className)}
    >
      <FieldLabel htmlFor={id} className={cn(!stacked && "pt-2 text-muted-foreground")}>
        {label}
      </FieldLabel>
      <FieldContent>
        <Slot.Root id={id}>{children}</Slot.Root>
        {description && <FieldDescription>{description}</FieldDescription>}
      </FieldContent>
    </Field>
  );
}
