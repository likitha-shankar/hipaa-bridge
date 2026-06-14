"""Runtime configuration, persisted as JSON next to the vault.

Written by the web UI's setup wizard; read by every entry point. Keeps the
"no coding" promise: nothing here requires editing files by hand, though the
JSON is plain enough that you can.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("hipaa_bridge_config.json")


@dataclass
class BridgeConfig:
    # "ollama" -> local model, "api" -> any OpenAI-compatible endpoint,
    # "none"  -> scrub/restore only, no AI calls at all.
    mode: str = "none"
    backend_url: str = "http://localhost:11434"
    api_key: str = ""
    model: str = "llama3.2"
    use_ner: bool = True
    vault_path: str = "hipaa_bridge_vault.db"
    setup_complete: bool = False
    # Watch-folder settings
    watch_in: str = "in"
    watch_out: str = "out"

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "BridgeConfig":
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text())
            known = {f for f in cls.__dataclass_fields__}
            return cls(**{k: v for k, v in data.items() if k in known})
        return cls()

    def save(self, path: str | Path = DEFAULT_CONFIG_PATH) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2))
