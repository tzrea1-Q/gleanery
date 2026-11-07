from gleanery.api.schemas import ModelPreset

PRESETS = [
    ModelPreset(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_style="responses",
        key_required=True,
    ),
    ModelPreset(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        api_style="chat",
        key_required=True,
    ),
    ModelPreset(
        id="qwen",
        name="通义",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_style="chat",
        key_required=True,
    ),
    ModelPreset(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_style="chat",
        key_required=True,
    ),
    ModelPreset(
        id="ollama",
        name="Ollama",
        base_url="http://127.0.0.1:11434/v1",
        api_style="chat",
        key_required=False,
    ),
    ModelPreset(id="custom", name="自定义", base_url="", api_style="chat", key_required=False),
    ModelPreset(
        id="anthropic",
        name="Anthropic",
        kind="anthropic",
        base_url="https://api.anthropic.com",
        api_style="messages",
        key_required=True,
    ),
]
