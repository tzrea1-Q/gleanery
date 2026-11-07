# 采集计划以草稿入库编辑，确认走 start_collection 审批闸门

Agent 调用 `propose_collection_plan` 把采集计划作为草稿写入 SQLite 并返回 `plan_id`；用户在工作区经 REST（`PATCH /api/plans/{id}`）编辑；Agent 再调用设了 `requires_approval=True` 的 `start_collection(plan_id)`，对话卡片与工作区按钮都只回应这次审批（批准，或拒绝并附理由），工具执行时从数据库读取最新计划。之所以绕一道 REST 而不在审批时改参：所选的 AI SDK v7 UI Message Stream 协议与 Pydantic AI `VercelAIAdapter` 只传 `approved` / `reason`（已核实源码），没有改参通道；计划落库还让它在应用重启、切换对话后依然可见可恢复。

## Considered Options

- **换 AG-UI 协议，用 interrupt 的 `editedArgs` 改参批准**：协议原生支持，但 assistant-ui 侧 interrupt API 仍为 experimental、`@assistant-ui/react-ag-ui` 处于 0.1.x。被否；若日后切到 AG-UI，可再评估。
- **human tool + `addResult` 回填完整计划**：需验证 Pydantic AI 对前端回填结果的处理，且计划只存在于消息里。被否。
