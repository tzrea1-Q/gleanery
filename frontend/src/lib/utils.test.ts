import { cn } from "./utils";

test("cn 合并 Tailwind 类名", () => {
  expect(cn("p-2", "p-4")).toBe("p-4");
});
