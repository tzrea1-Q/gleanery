import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


def fake_anthropic(
    status: int = 200, no_tool: bool = False, missing_models: bool = False
) -> FastAPI:
    app = FastAPI()
    app.state.requests = []

    @app.get("/v1/models")
    async def models(request: Request) -> JSONResponse:
        app.state.requests.append(request)
        if (
            request.headers.get("x-api-key") != "test-key"
            or request.headers.get("anthropic-version") != "2023-06-01"
        ):
            return JSONResponse({}, status_code=401)
        if missing_models or status != 200:
            return JSONResponse({}, status_code=404 if missing_models else status)
        after = request.query_params.get("after_id")
        assert request.query_params.get("limit") == "1000"
        return JSONResponse(
            {
                "data": [
                    {
                        "id": "model-2" if after else "model-1",
                        "display_name": "模型二" if after else "模型一",
                    }
                ],
                "has_more": not after,
                "last_id": "model-2" if after else "model-1",
            }
        )

    @app.post("/v1/messages")
    async def messages(request: Request):
        body = await request.json()
        app.state.requests.append((request, body))
        if request.headers.get("authorization") != "Bearer test-key":
            return JSONResponse(
                {"error": {"type": "authentication_error", "message": "failed"}}, status_code=401
            )
        if status != 200:
            return JSONResponse(
                {"error": {"type": "error", "message": "failed"}}, status_code=status
            )
        block = (
            {"type": "text", "text": "hello"}
            if no_tool
            else {"type": "tool_use", "id": "tool_1", "name": "probe", "input": {}}
        )
        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "model-1",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            },
            {"type": "content_block_start", "index": 0, "content_block": block},
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": "end_turn" if no_tool else "tool_use",
                    "stop_sequence": None,
                },
                "usage": {"output_tokens": 1},
            },
            {"type": "message_stop"},
        ]
        return StreamingResponse(
            iter(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events),
            media_type="text/event-stream",
        )

    return app
