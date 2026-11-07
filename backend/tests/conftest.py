from pydantic_ai import models

# 自动化测试不接真模型。
models.ALLOW_MODEL_REQUESTS = False
