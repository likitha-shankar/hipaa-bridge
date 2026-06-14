"""De-identifying proxy for any OpenAI-compatible chat backend.

Point your app at this proxy instead of the backend. Outbound message text
is scrubbed (PHI -> tokens) before it leaves the machine; inbound responses
are restored (tokens -> PHI) locally. Works with Ollama out of the box
(`ollama serve` exposes /v1/chat/completions), or any other compatible
endpoint via --backend.

Streaming responses are restored chunk-by-chunk with holdback buffering so
tokens split across SSE chunks are still caught.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .sanitizer import StreamRestorer, restore, scrub
from .vault import TokenVault


def _scrub_payload(payload: dict[str, Any], vault: TokenVault, use_ner: bool) -> dict[str, Any]:
    """Scrub every text field in an OpenAI-style chat payload."""
    scrubbed = dict(payload)
    messages = []
    for msg in payload.get("messages", []):
        msg = dict(msg)
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = scrub(content, vault, use_ner=use_ner).text
        elif isinstance(content, list):  # multimodal block list
            blocks = []
            for block in content:
                block = dict(block)
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    block["text"] = scrub(block["text"], vault, use_ner=use_ner).text
                blocks.append(block)
            msg["content"] = blocks
        messages.append(msg)
    scrubbed["messages"] = messages
    return scrubbed


def _restore_response(body: dict[str, Any], vault: TokenVault) -> dict[str, Any]:
    for choice in body.get("choices", []):
        message = choice.get("message")
        if message and isinstance(message.get("content"), str):
            message["content"] = restore(message["content"], vault)
    return body


async def _restore_sse(
    upstream: AsyncIterator[bytes], vault: TokenVault
) -> AsyncIterator[bytes]:
    """Rewrite content deltas inside an SSE stream, holding back partial tokens."""
    restorer = StreamRestorer(vault)
    pending = b""
    async for raw in upstream:
        pending += raw
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            text = line.decode("utf-8", errors="replace").rstrip("\r")
            if not text.startswith("data:"):
                yield line + b"\n"
                continue
            data = text[5:].strip()
            if data == "[DONE]":
                tail = restorer.flush()
                if tail:
                    yield _delta_event(tail)
                yield line + b"\n"
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                yield line + b"\n"
                continue
            delta = (event.get("choices") or [{}])[0].get("delta", {})
            content = delta.get("content")
            if isinstance(content, str) and content:
                delta["content"] = restorer.feed(content)
            yield f"data: {json.dumps(event)}\n".encode()
    tail = restorer.flush()
    if tail:
        yield _delta_event(tail)


def _delta_event(text: str) -> bytes:
    event = {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
    return f"data: {json.dumps(event)}\n\n".encode()


def create_app(
    backend_url: str = "http://localhost:11434",
    vault_path: str = "hipaa_bridge_vault.db",
    use_ner: bool = True,
    config: "BridgeConfig | None" = None,
) -> FastAPI:
    from .config import BridgeConfig
    from .webui import attach_webui

    app = FastAPI(title="HIPAA-Bridge Proxy")
    vault = TokenVault(vault_path)
    backend = backend_url.rstrip("/")

    if config is None:
        config = BridgeConfig.load()
        config.backend_url = backend
        config.vault_path = str(vault_path)
        config.use_ner = use_ner
    attach_webui(app, config, vault)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "backend": backend, "vault_entries": sum(vault.stats().values())}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        payload = await request.json()
        scrubbed = _scrub_payload(payload, vault, use_ner)
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() in ("authorization", "content-type")
        }

        if scrubbed.get("stream"):
            client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0))
            upstream_req = client.build_request(
                "POST", f"{backend}/v1/chat/completions", json=scrubbed, headers=headers
            )
            upstream = await client.send(upstream_req, stream=True)

            async def body() -> AsyncIterator[bytes]:
                try:
                    async for chunk in _restore_sse(upstream.aiter_bytes(), vault):
                        yield chunk
                finally:
                    await upstream.aclose()
                    await client.aclose()

            return StreamingResponse(
                body(),
                status_code=upstream.status_code,
                media_type="text/event-stream",
            )

        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
            resp = await client.post(
                f"{backend}/v1/chat/completions", json=scrubbed, headers=headers
            )
        try:
            body_json = resp.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "backend returned non-JSON"}, status_code=502)
        return JSONResponse(_restore_response(body_json, vault), status_code=resp.status_code)

    return app
