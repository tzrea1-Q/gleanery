import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


def fake_openai(status: int = 200, no_tool: bool = False, missing_models: bool = False) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/models")
    async def models() -> JSONResponse:
        return JSONResponse(
            {"data": [{"id": "fake-model"}]}, status_code=404 if missing_models else status
        )

    @app.post("/v1/chat/completions")
    async def completion(request: Request):
        if status != 200:
            return JSONResponse(
                {"error": {"message": "failed", "type": "error"}}, status_code=status
            )
        body = await request.json()
        if body.get("tools") and not no_tool:
            delta = {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": body["tools"][0]["function"]["name"],
                            "arguments": "{}",
                        },
                    }
                ]
            }
            finish = "tool_calls"
        else:
            delta, finish = {"content": "hello"}, "stop"
        chunks = [
            {
                "id": "chat_1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fake-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            },
            {
                "id": "chat_1",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fake-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
        ]
        return StreamingResponse(
            iter([*(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks), "data: [DONE]\n\n"]),
            media_type="text/event-stream",
        )

    return app
