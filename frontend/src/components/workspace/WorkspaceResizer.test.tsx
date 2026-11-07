import { fireEvent, render, screen } from "@testing-library/react";
import { useWorkspace } from "@/stores/workspace";
import { WorkspaceResizer } from "./WorkspaceResizer";

function setup() {
  render(
    <div data-testid="grid">
      <div data-testid="chat" />
      <div data-testid="panel">
        <WorkspaceResizer />
      </div>
    </div>,
  );
  const width = (id: string, value: number) =>
    vi
      .spyOn(screen.getByTestId(id), "getBoundingClientRect")
      .mockReturnValue({ width: value } as DOMRect);
  width("chat", 600);
  width("panel", 400);
  return screen.getByRole("separator", { name: "调整工作区宽度" });
}

afterEach(() => {
  useWorkspace.setState({ wide: false, widths: { standard: null, wide: null } });
  localStorage.clear();
  vi.restoreAllMocks();
});

test("向左拖动加宽，松手才写入并记住", () => {
  const handle = setup();
  fireEvent.pointerDown(handle, { button: 0, clientX: 500, pointerId: 1 });
  fireEvent.pointerMove(handle, { clientX: 400, pointerId: 1 });
  expect(screen.getByTestId("grid").style.getPropertyValue("--workspace-width")).toBe("500px");
  expect(useWorkspace.getState().widths.standard).toBeNull();
  fireEvent.pointerUp(handle, { pointerId: 1 });
  expect(useWorkspace.getState().widths.standard).toBe(500);
  expect(JSON.parse(localStorage.getItem("gleanery.workspaceWidths")!)).toMatchObject({
    standard: 500,
  });
});

test("拖动不能超过对话栏和工作区的最小宽度", () => {
  const handle = setup();
  fireEvent.pointerDown(handle, { button: 0, clientX: 500, pointerId: 1 });
  fireEvent.pointerMove(handle, { clientX: -1000, pointerId: 1 });
  fireEvent.pointerUp(handle, { pointerId: 1 });
  expect(useWorkspace.getState().widths.standard).toBe(660);
  fireEvent.pointerDown(handle, { button: 0, clientX: 500, pointerId: 1 });
  fireEvent.pointerMove(handle, { clientX: 2000, pointerId: 1 });
  fireEvent.pointerUp(handle, { pointerId: 1 });
  expect(useWorkspace.getState().widths.standard).toBe(320);
});

test("只点一下不固定宽度，双击恢复默认", () => {
  const handle = setup();
  fireEvent.pointerDown(handle, { button: 0, clientX: 500, pointerId: 1 });
  fireEvent.pointerUp(handle, { pointerId: 1 });
  expect(useWorkspace.getState().widths.standard).toBeNull();
  useWorkspace.getState().setWidth(500);
  fireEvent.doubleClick(handle);
  expect(useWorkspace.getState().widths.standard).toBeNull();
});

test("方向键调整宽度，宽窄两档各记各的", () => {
  const handle = setup();
  fireEvent.keyDown(handle, { key: "ArrowLeft" });
  expect(useWorkspace.getState().widths.standard).toBe(424);
  useWorkspace.setState({ wide: true });
  fireEvent.keyDown(handle, { key: "ArrowRight" });
  expect(useWorkspace.getState().widths).toEqual({ standard: 424, wide: 376 });
});
