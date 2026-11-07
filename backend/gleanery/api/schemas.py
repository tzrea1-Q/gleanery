"""M0 的 REST 契约。前端类型经 openapi-typescript 从这里生成，改动后跑 `just gen-api`。

时间一律是 UTC 毫秒时间戳。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------- 对话 ----------


class ConversationSummary(BaseModel):
    id: int
    title: str
    """首条用户消息的截取；还没有消息时为空串，界面显示"新对话"。"""
    created_at: int
    updated_at: int


class ConversationDetail(ConversationSummary):
    messages: list[dict[str, Any]]
    """AI SDK v7 的 UIMessage 列表，由 `VercelAIAdapter.dump_messages` 生成。
    Agent 消息的 `metadata.model` 是生成它的模型名；事件消息的 `metadata.gleanery_event` 有值。"""
    running: Literal["chat", "follow_up"] | None = None
    """这个对话正在运行的一轮 Agent 的来源；空闲时为 None。"""


# ---------- 模型配置 ----------

ApiStyle = Literal["responses", "chat", "messages"]
ConfigKind = Literal["openai_compatible", "anthropic", "chatgpt_plan"]
ConfigStatus = Literal["ok", "unavailable", "needs_reconnect"]
ToolTestStatus = Literal["untested", "ok", "failed"]


class ModelPreset(BaseModel):
    id: Literal["openai", "deepseek", "qwen", "openrouter", "ollama", "custom", "anthropic"]
    kind: ConfigKind = "openai_compatible"
    name: str
    base_url: str
    """custom 预设为空串，由用户填写。"""
    api_style: ApiStyle
    key_required: bool


class FavoriteModel(BaseModel):
    """模型配置下勾选的常用模型。只有 `tool_test == "ok"` 的能选为当前模型。"""

    name: str
    tool_test: ToolTestStatus
    tool_test_error: str | None = None
    tested_at: int | None = None


class ModelConfigOut(BaseModel):
    id: int
    kind: ConfigKind
    name: str
    preset: str
    base_url: str
    api_style: ApiStyle
    status: ConfigStatus
    status_reason: str | None = None
    """不可用的原因，如"凭证无效（401）""连接失败"。"""
    has_credential: bool
    """凭证本身永不返回给前端。ChatGPT 套餐的含义是"有 refresh token"。"""
    available_models: list[str] | None = None
    """`GET /models` 的缓存结果；为 None 表示没拉到，界面改为手填。"""
    model_labels: dict[str, str] | None = None
    """模型 ID 到显示名。接口给了显示名时才有，请求和 `favorites[].name` 永远用 ID。"""
    models_fetched_at: int | None = None
    favorites: list[FavoriteModel]
    created_at: int
    updated_at: int


class ModelConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    preset: str
    base_url: str = Field(min_length=1)
    api_key: str | None = None
    """本地模型（如 Ollama）可以为空。"""


class ModelConfigUpdate(BaseModel):
    """未给出的字段保持不变。`api_key` 为空串表示清除凭证。改了 base_url 或 api_key 会重测连通。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1)
    api_key: str | None = None


class FavoriteAdd(BaseModel):
    model: str = Field(min_length=1)


# ---------- 应用状态 ----------


class CurrentModel(BaseModel):
    config_id: int
    config_name: str
    kind: ConfigKind
    model: str
    status: ConfigStatus
    """配置不可用或该模型的工具调用测试不是 ok 时不为 ok，此时输入框禁用。
    ChatGPT 套餐失效时是 needs_reconnect。"""
    status_reason: str | None = None


class CurrentModelSet(BaseModel):
    config_id: int
    model: str


class AppState(BaseModel):
    current_model: CurrentModel | None
    """为 None 时输入框禁用，对话区显示"先选一个模型"卡片。"""
    disclaimer_acknowledged: bool
    """首次启动的使用声明是否已点过"我知道了"。"""
    chatgpt_notice_acknowledged: bool
    """首次连上 ChatGPT 套餐时的额度说明是否已点过"我知道了"。"""
    credential_backend: Literal["keyring", "file", "memory"]
    """为 file 时设置里明示"凭证以明文文件保存"。"""
