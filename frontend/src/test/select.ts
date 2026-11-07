import { screen } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";

/** 在 FormSelect 上选一项。Radix 的 Select 不是原生控件，不能用 `selectOptions`。 */
export async function pickOption(user: UserEvent, label: string | HTMLElement, option: string) {
  await user.click(typeof label === "string" ? screen.getByLabelText(label) : label);
  await user.click(await screen.findByRole("option", { name: option }));
}
