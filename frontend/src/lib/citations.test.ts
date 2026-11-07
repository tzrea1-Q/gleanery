import { expect, test } from "vitest";
import cases from "../../../backend/tests/report/citation_cases.json";
import { citationLabel, parseCitations } from "./citations";

/** 用例表的位置按码点计（与 Python 一致），换算成 JS 的 UTF-16 下标。 */
const utf16 = (text: string, index: number) => Array.from(text).slice(0, index).join("").length;

for (const item of cases) {
  test(item.name, () => {
    expect(parseCitations(item.text)).toEqual(
      item.markers.map(({ too_many, start, end, ...marker }) => ({
        ...marker,
        start: utf16(item.text, start),
        end: utf16(item.text, end),
        tooMany: too_many,
      })),
    );
  });
}

test("引用标签", () => {
  expect(citationLabel({ kind: "content", id: 123 })).toBe("c:123");
  expect(citationLabel({ kind: "comment", id: 456 })).toBe("m:456");
});
