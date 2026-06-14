"""Scrub and restore: the two halves of the bridge.

scrub()   — detect PHI spans, replace each with its deterministic vault token.
restore() — replace tokens back with original values, tolerating the ways
            LLMs mangle tokens in responses (dropped brackets, case drift).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .detectors import detect
from .vault import TokenVault

# Matches our token format both intact "[PATIENT_9A4F1B22]" and with the
# brackets dropped by a model: "PATIENT_9A4F1B22".
_TOKEN_RE = re.compile(r"\[?([A-Z]+_[0-9A-F]{8,64})\]?")


@dataclass
class ScrubResult:
    text: str
    replacements: list[tuple[str, str, str]] = field(default_factory=list)  # (category, value, token)

    @property
    def count(self) -> int:
        return len(self.replacements)


def scrub(text: str, vault: TokenVault, use_ner: bool = True) -> ScrubResult:
    spans = detect(text, use_ner=use_ner)
    out: list[str] = []
    cursor = 0
    replacements: list[tuple[str, str, str]] = []
    for span in spans:
        token = vault.tokenize(span.category, span.value)
        out.append(text[cursor:span.start])
        out.append(token)
        replacements.append((span.category, span.value, token))
        cursor = span.end
    out.append(text[cursor:])
    return ScrubResult(text="".join(out), replacements=replacements)


def restore(text: str, vault: TokenVault) -> str:
    def _sub(m: re.Match[str]) -> str:
        bare = m.group(1)
        value = vault.lookup(f"[{bare}]")
        return value if value is not None else m.group(0)

    return _TOKEN_RE.sub(_sub, text)


class StreamRestorer:
    """Restore tokens across a stream of text chunks.

    A token can be split across chunk boundaries, so we hold back any suffix
    that could be the start of a token and emit it once resolved.
    """

    # Longest token we ever emit: "[" + category + "_" + 64 hex + "]"
    _MAX_TOKEN_LEN = 96
    _PARTIAL_RE = re.compile(r"\[?[A-Z]*(?:_[0-9A-F]*)?\]?$")

    def __init__(self, vault: TokenVault):
        self.vault = vault
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        # Find the earliest position from which a partial token could extend
        # past the end of the buffer; emit everything before it.
        holdback_at = len(self._buffer)
        window_start = max(0, len(self._buffer) - self._MAX_TOKEN_LEN)
        for i in range(window_start, len(self._buffer)):
            ch = self._buffer[i]
            if ch == "[" or (ch.isupper() and ch.isalpha()):
                tail = self._buffer[i:]
                if self._PARTIAL_RE.fullmatch(tail) and len(tail) < self._MAX_TOKEN_LEN:
                    holdback_at = i
                    break
        emit, self._buffer = self._buffer[:holdback_at], self._buffer[holdback_at:]
        return restore(emit, self.vault)

    def flush(self) -> str:
        out = restore(self._buffer, self.vault)
        self._buffer = ""
        return out
