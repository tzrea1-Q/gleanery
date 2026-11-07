import base64
import hashlib
import json
import time
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


def jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"e30.{payload}.signature"


def _completed_stream() -> str:
    response = {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "model": "fake-model",
        "output": [],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }
    item = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "你好", "annotations": []}],
    }
    events = [
        {"type": "response.created", "response": {**response, "status": "in_progress"}},
        {
            "type": "response.output_item.added",
            "item": {**item, "status": "in_progress", "content": []},
            "output_index": 0,
        },
        {
            "type": "response.content_part.added",
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        },
        {
            "type": "response.output_text.delta",
            "item_id": "msg_1",
            "output_index": 0,
            "content_index": 0,
            "delta": "你好",
            "logprobs": [],
        },
        {"type": "response.output_item.done", "item": item, "output_index": 0},
        {
            "type": "response.completed",
            "response": {**response, "status": "completed", "output": [item]},
        },
    ]
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': number})}\n\n"
        for number, event in enumerate(events)
    )


class FakeSIWC:
    def __init__(self) -> None:
        self.app = FastAPI()
        self.challenge = ""
        self.nonce = ""
        self.scope = "openid offline_access chatgpt.tokens.use.direct"
        self.refresh_count = 0
        self.reject_refresh = False
        self.revoke_status = 200
        self.revocations = 0
        self.expired = False
        self.requests: list[tuple[dict, str]] = []
        self.token_clients: list[str] = []
        self.failed_stream = True
        self.responses_status = 200
        self.subject = "user"
        self.app.add_api_route("/.well-known/openid-configuration", self.discovery)
        self.app.add_api_route("/api/accounts/oauth/token", self.token, methods=["POST"])
        self.app.add_api_route("/revoke", self.revoke, methods=["POST"])
        self.app.add_api_route("/v1/models", self.models)
        self.app.add_api_route("/v1/responses", self.responses, methods=["POST"])

    async def discovery(self, request: Request) -> JSONResponse:
        assert request.url.hostname == "auth.openai.com"
        return JSONResponse({"revocation_endpoint": "https://auth.openai.com/revoke"})

    async def token(self, request: Request) -> JSONResponse:
        assert request.url.hostname == "auth.openai.com"
        form = parse_qs((await request.body()).decode())
        self.token_clients.append(form["client_id"][0])
        if form["grant_type"] == ["authorization_code"]:
            digest = hashlib.sha256(form["code_verifier"][0].encode()).digest()
            assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == self.challenge
        else:
            self.refresh_count += 1
            if self.reject_refresh:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
        now = int(time.time())
        access = jwt({"exp": now - 10 if self.expired and self.refresh_count == 0 else now + 3600})
        identity = jwt(
            {
                "iss": "https://auth.openai.com",
                "aud": form["client_id"][0],
                "sub": self.subject,
                "nonce": self.nonce,
                "exp": now + 3600,
            }
        )
        return JSONResponse(
            {
                "access_token": access,
                "refresh_token": f"refresh-{self.refresh_count}",
                "id_token": identity,
                "scope": self.scope,
            }
        )

    async def revoke(self, request: Request) -> Response:
        assert request.url.hostname == "auth.openai.com"
        self.revocations += 1
        return Response(status_code=self.revoke_status)

    async def models(self, request: Request) -> JSONResponse:
        assert request.url.hostname == "api.openai.com"
        assert request.headers["authorization"].startswith("Bearer ")
        if self.reject_refresh:
            return JSONResponse({"error": {"message": "expired"}}, status_code=401)
        return JSONResponse(
            {
                "data": [
                    {"slug": "fake-model", "display_name": "假模型", "visibility": "list"},
                    {"slug": "hidden", "visibility": "hidden"},
                ]
            }
        )

    async def responses(self, request: Request) -> Response:
        assert request.url.hostname == "api.openai.com"
        self.requests.append((await request.json(), request.headers["authorization"]))
        if self.reject_refresh:
            return JSONResponse({"error": {"message": "expired"}}, status_code=401)
        if self.responses_status != 200:
            return JSONResponse(
                {"error": {"code": "rate_limit_exceeded", "message": "slow down"}},
                status_code=self.responses_status,
            )
        if not self.failed_stream:
            return Response(_completed_stream(), media_type="text/event-stream")
        event = {
            "type": "response.failed",
            "sequence_number": 0,
            "response": {
                "id": "resp_1",
                "object": "response",
                "created_at": 1,
                "model": "fake-model",
                "status": "failed",
                "output": [],
                "error": {"code": "subscription_sharing_usage_limit_exceeded", "message": "quota"},
            },
        }
        return Response(
            f"event: response.failed\ndata: {json.dumps(event)}\n\n", media_type="text/event-stream"
        )
