"""Web UI + JSON API: setup wizard, scrub/restore workbench, audit view.

Mounted on top of the proxy app, so one process serves:
  /                      browser UI (wizard on first run, workbench after)
  /api/config            GET current config, POST to save (wizard submit)
  /api/scrub             POST {text} -> {text, replacements}   (Mirth-friendly)
  /api/restore           POST {text} -> {text}                 (Mirth-friendly)
  /api/ask               POST {text} -> scrub -> AI backend -> restore
  /api/audit             GET vault category counts
  /v1/chat/completions   OpenAI-compatible de-identifying proxy (proxy.py)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .config import BridgeConfig
from .detectors import ner_available
from .sanitizer import restore, scrub
from .vault import TokenVault

_STATIC = Path(__file__).parent / "static" / "index.html"


class TextIn(BaseModel):
    text: str


class ConfigIn(BaseModel):
    mode: str
    backend_url: str = "http://localhost:11434"
    api_key: str = ""
    model: str = "llama3.2"
    use_ner: bool = True


def attach_webui(app: FastAPI, config: BridgeConfig, vault: TokenVault) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _STATIC.read_text()

    @app.get("/api/config")
    async def get_config() -> dict[str, Any]:
        return {
            "mode": config.mode,
            "backend_url": config.backend_url,
            "model": config.model,
            "use_ner": config.use_ner,
            "setup_complete": config.setup_complete,
            "ner_available": ner_available(),
            "api_key_set": bool(config.api_key),
        }

    @app.post("/api/config")
    async def set_config(body: ConfigIn) -> dict[str, Any]:
        config.mode = body.mode
        config.backend_url = body.backend_url.rstrip("/")
        if body.api_key:
            config.api_key = body.api_key
        config.model = body.model
        config.use_ner = body.use_ner
        config.setup_complete = True
        config.save()
        return {"ok": True}

    @app.post("/api/scrub")
    async def api_scrub(body: TextIn) -> dict[str, Any]:
        result = scrub(body.text, vault, use_ner=config.use_ner)
        return {
            "text": result.text,
            "replacements": [
                {"category": c, "token": t} for c, _v, t in result.replacements
            ],
            "count": result.count,
        }

    @app.post("/api/restore")
    async def api_restore(body: TextIn) -> dict[str, Any]:
        return {"text": restore(body.text, vault)}

    @app.post("/api/ask")
    async def api_ask(body: TextIn):
        if config.mode == "none":
            return JSONResponse(
                {"error": "AI disabled in setup — scrub-only mode"}, status_code=400
            )
        scrubbed = scrub(body.text, vault, use_ner=config.use_ner)
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        payload = {
            "model": config.model,
            "messages": [{"role": "user", "content": scrubbed.text}],
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
                resp = await client.post(
                    f"{config.backend_url}/v1/chat/completions", json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return JSONResponse({"error": f"backend unreachable: {exc}"}, status_code=502)
        answer = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return {
            "scrubbed_prompt": scrubbed.text,
            "scrubbed_count": scrubbed.count,
            "raw_answer": answer,
            "answer": restore(answer, vault),
        }

    @app.get("/api/audit")
    async def api_audit() -> dict[str, Any]:
        stats = vault.stats()
        return {"categories": stats, "total": sum(stats.values())}
