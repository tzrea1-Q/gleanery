import { expect, test } from "vitest";
import { formatDate, formatDateTime } from "./format";

test("按本地时区输出，个位补零", () => {
  const ms = new Date(2024, 0, 5, 3, 7, 9).getTime();
  expect(formatDateTime(ms)).toBe("2024-01-05 03:07");
  expect(formatDateTime(ms, { seconds: true })).toBe("2024-01-05 03:07:09");
  expect(formatDate(ms)).toBe("2024-01-05");
});
