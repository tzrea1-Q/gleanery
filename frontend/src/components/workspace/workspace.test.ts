import { useWorkspace } from "@/stores/workspace";

test("编辑中不抢走标签，主动选择后清除提醒", () => {
  useWorkspace.setState({ tab: "plan", editing: true, dirty: false, notices: [] });
  useWorkspace.getState().auto("collect");
  expect(useWorkspace.getState().tab).toBe("plan");
  expect(useWorkspace.getState().notices).toEqual(["collect"]);
  useWorkspace.getState().select("collect");
  expect(useWorkspace.getState().tab).toBe("collect");
  expect(useWorkspace.getState().notices).toEqual([]);
  useWorkspace.setState({ tab: "plan", editing: false, dirty: true });
  useWorkspace.getState().auto("dataset");
  expect(useWorkspace.getState().tab).toBe("plan");
  expect(useWorkspace.getState().notices).toContain("dataset");
  useWorkspace.setState({ tab: "plan", editing: false, dirty: false, notices: [] });
});
