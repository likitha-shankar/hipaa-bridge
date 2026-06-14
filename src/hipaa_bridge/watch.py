"""Watch-folder mode: drop files in, scrubbed copies come out.

Built for the honest-broker / research-data workflow: an analyst exports
notes from the clinical data warehouse, drops them into `in/`, and collects
de-identified copies from `out/`. No terminal, no code — a shared folder.

Polling (no extra dependency); a file is picked up once its size is stable
across two polls, then moved to `in/processed/`.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from .sanitizer import scrub
from .vault import TokenVault

_TEXT_SUFFIXES = {".txt", ".md", ".csv", ".hl7", ".json", ".xml", ".rtf"}


def watch(
    in_dir: str | Path,
    out_dir: str | Path,
    vault: TokenVault,
    use_ner: bool = True,
    poll_seconds: float = 2.0,
    once: bool = False,
) -> int:
    """Run the watcher. Returns number of files processed (useful with once=True)."""
    in_path, out_path = Path(in_dir), Path(out_dir)
    processed_path = in_path / "processed"
    for p in (in_path, out_path, processed_path):
        p.mkdir(parents=True, exist_ok=True)

    sizes: dict[Path, int] = {}
    total = 0
    print(f"watching {in_path.resolve()} -> {out_path.resolve()} (ctrl-c to stop)")

    while True:
        for f in sorted(in_path.iterdir()):
            if not f.is_file() or f.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            size = f.stat().st_size
            if not once and sizes.get(f) != size:
                sizes[f] = size  # wait one more poll for the writer to finish
                continue
            sizes.pop(f, None)

            try:
                text = f.read_text(errors="replace")
            except OSError as exc:
                print(f"  skip {f.name}: {exc}")
                continue
            result = scrub(text, vault, use_ner=use_ner)
            (out_path / f.name).write_text(result.text)
            shutil.move(str(f), processed_path / f.name)
            total += 1
            print(f"  {f.name}: {result.count} item(s) de-identified")

        if once:
            return total
        time.sleep(poll_seconds)
