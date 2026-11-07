# 前端界面规范

改 `frontend/src/` 下的页面、组件或样式时按这份做。为什么这样定，见 [ADR-0007](adr/0007-shadcn-with-fixed-design-language.md)。

颜色和圆角的取值在 `frontend/src/index.css`，那里是唯一来源。这份文档只讲怎么用。

## 风格

1. **面板**：灰色画布上放白色悬浮面板，靠间距分区。卡片不描边、不加阴影，边框只用于表格行和输入框。
2. **字号层级**：标题和正文要拉开，取值见下表。大字都加 `tracking-tight`。
3. **墨黑主操作**：每个区域最多一个实心按钮，放在这个区域最终决定的动作上。其余用 `outline` 或 `ghost`，列表里每行重复的操作也一样。
4. **状态色**：颜色只表达状态，取值见下表。
5. **一个重点色块**：一屏最多一块整块着色，留给当前最重要的结果，比如采集全部完成的卡片。
6. **结论先行**：卡片标题写结论或要做的决定，细节放在下面。
7. **清单**：需要核对的信息写成"状态图标 + 标签 + 右对齐的值"，参考 `PlanChecklist`。
8. **两行信息**：列表主行放标题，副行放平台、作者、时间，以此减少列数。
9. **浅底表头**：表头是圆角浅灰条，行之间只留细线。
10. **软底图标**：状态图标放在有底色的圆形里。图标都用 `lucide-react`。

### 状态色

| Token | 含义 |
|---|---|
| `success` / `success-muted` | 完成 |
| `brand` / `brand-muted` | 进行中、选中、焦点 |
| `attention` / `attention-muted` | 要处理：暂停、错误 |
| `warning` / `warning-muted` | 提示、定位高亮 |
| `muted` | 未开始、次要 |
| `destructive` | 不可恢复的操作 |
| `lime` | Logo 和勾选图标，上面用墨黑字 |
| `platform-xhs`、`platform-bili` | 只用于平台标签 |

新颜色先在 `index.css` 加语义 token，亮色和暗色都要给值，文字和底色对比度不低于 4.5。

### 字号和形状

| 元素 | 写法 |
|---|---|
| 页面标题 | `text-3xl font-semibold tracking-tight`，对话标题用 `text-2xl`，首页用 `text-4xl` |
| 卡片标题 | `text-xl font-semibold tracking-tight` |
| 关键数字 | `text-3xl font-semibold tracking-tight tabular-nums` |
| 正文 | 默认 14px，不写字号 |
| 辅助文字 | `text-xs text-muted-foreground` |
| 表格 | `text-[13px]`，数字列 `tabular-nums` 右对齐 |
| 大面板 | `rounded-3xl bg-card` |
| 卡片 | `rounded-2xl bg-card` |
| 卡片里的分组 | `rounded-2xl bg-muted/60 dark:bg-muted/40` |
| 内层小块 | `rounded-xl` |
| 工具条上的控件 | `rounded-full border-0 bg-muted shadow-none dark:bg-muted` |

输入框和按钮的形状由组件自带。

## 布局

- 三栏：左栏、对话、工作区。对话栏任何窗口下都保住 340px。
- 工作区有两档：计划、采集用标准档，数据集、报告用宽档。用户拖出的宽度两档分开记。
- 窗口不足 1280px 时，左栏启动时收成图标栏。不足 768px 时左栏变抽屉，工作区排到对话下方。
- 独立页面（所有数据集、所有报告、平台账号）用同一个骨架：左边大标题加一行概况，右边筛选和搜索，下面是卡片网格。条目数量会增长的内容都放这里，侧栏只留入口和需要处理的数量。
- 隐藏工作区时保持挂载，未保存的编辑和进行中的定位请求才不会丢。
- 吸底操作栏写 `sticky bottom-0 -mx-4 -mb-4 border-t bg-card px-4 py-3`，放在工作区内容的最后。

## 组件选型

业务代码用下表的组件。手写 `button`、`input`、`select`、`textarea` 和 `window.confirm` 过不了 lint。

| 需求 | 用什么 |
|---|---|
| 按钮 | `Button`；链接按钮用 `asChild` 包 `a` |
| 表单行 | `FormRow`，默认两列，窄处用 `stacked` |
| 下拉 | `FormSelect`；要分组时用 `Select` |
| 勾选 | `CheckRow` |
| 对话里的卡片 | `ChatCard`，带 `aria-label` |
| 错误和警告 | `Notice` |
| 状态 | `StatusBadge` |
| 平台 | `PlatformTag`、`platformName` |
| 确认 | `askConfirm` |
| 空结果 | `Empty` |
| 首次加载 | `Skeleton`，外层 `role="status"` 加 `aria-label` |
| 列表项 | `Item` |
| 数据表 | `Table` |
| 折叠分组 | `Collapsible` |
| 操作菜单 | `DropdownMenu` |
| 筛选和详情浮层 | `Popover` |
| 时间 | `formatDateTime`、`formatDate` |

同样的样式第三次出现时，提到 `src/components/common/`。

### 容易踩的点

- 菜单项要弹确认框时，`DropdownMenu` 写 `modal={false}`。模态菜单收起时会把 `body` 的 `pointer-events` 留在 `none`。
- `fieldset disabled` 管不到 Radix 控件，`FormSelect`、`CheckRow` 要自己传 `disabled`。
- `FormSelect` 没有原生校验。必选时，在没选的情况下禁用提交按钮。
- 工作区的滚动容器不留底部 padding，留白放在内层。Chromium 算吸底位置时会扣掉滚动容器的 padding，操作栏下面会漏出内容。
- 下拉弹层在 Portal 里，焦点离开表单时要确认"正在编辑"的状态没有丢，`Workspace.test.tsx` 有对应用例。

## 交互

| 情况 | 做法 |
|---|---|
| 阻断当前区域的错误、风控、冲突 | 就地 `Notice`，不自动消失 |
| 操作成功的短暂结果 | `sonner` 的 toast |
| 风控 | 进度卡片和工作区都显示，不在前台时发系统通知 |
| 不可恢复的操作 | `destructive` 按钮，经过 `askConfirm` |
| 要先看影响再确认 | 就地面板，`role="alertdialog"`，比如"删除所有采集数据" |
| 进行中 | 禁用按钮，保持按钮名称不变 |
| 空数据 | `Empty`，能给下一步时写出下一步 |

用户正在编辑的标签不被抢走，新内容只亮提醒。用户关掉工作区后，Agent 推进阶段不重新打开它，用户点进工作区的入口才打开。

文案用中文，直接写结果和下一步。

## 生成组件

`src/components/ui/` 和 `src/components/assistant-ui/` 是生成的，要改样式先看能不能用 `className` 解决。已经为设计语言改过的地方：`button`、`dialog`、`alert-dialog` 的外形，`sidebar` 的悬浮面板，`thread.aui.tsx` 的输入框。

加 shadcn 组件：

1. 运行 `npx shadcn@4.8.3 add <组件>`，不加 `--overwrite`。`pnpm dlx` 会报错。
2. `git checkout` 恢复被覆盖的现有组件，保住上面那些改动。
3. 把新文件里的 `from "cn"` 改成 `from "@/lib/utils"`。
4. 恢复 `package.json` 和 `pnpm-lock.yaml`。

需要新依赖的组件（`Command`、`Calendar`、`Resizable`、`Combobox`、`@tanstack/react-table`）目前都不用。工作区的拖动条是手写的 `WorkspaceResizer`。

## 测试

- 按角色和名称找元素，所以 `aria-label`、按钮文字都算接口，改了要同步测试。
- Radix 的 `Select` 用 `src/test/select.ts` 的 `pickOption`。
- 确认框的用例要渲染 `<ConfirmHost />`。
- 项目不做截图回归，视觉靠走查。

## 完成标准

改完界面，下面都做到才算完成：

- `just check-frontend` 和 `just e2e` 通过。
- 改动涉及的页面，在 1440 和 1024 宽度、亮色和暗色四种组合下都实际看过，没有横向溢出和文字截断。
- 风格 10 条逐条对过，新增的颜色、圆角、字号都能在这份文档里找到出处。
