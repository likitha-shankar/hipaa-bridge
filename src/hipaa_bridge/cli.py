"""Command-line interface.

    hipaa-bridge scrub   note.txt              # PHI -> tokens, prints result
    hipaa-bridge restore response.txt          # tokens -> PHI
    hipaa-bridge audit                         # vault contents summary
    hipaa-bridge serve --backend http://localhost:11434  # start local proxy

Reads stdin when no file is given, so it pipes:
    cat note.txt | hipaa-bridge scrub | ollama run llama3.2 | hipaa-bridge restore
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .detectors import ner_available
from .sanitizer import restore, scrub
from .vault import TokenVault


def _read_input(path: str | None) -> str:
    if path and path != "-":
        return Path(path).read_text()
    return sys.stdin.read()


def _cmd_scrub(args: argparse.Namespace) -> int:
    vault = TokenVault(args.vault)
    result = scrub(_read_input(args.file), vault, use_ner=not args.no_ner)
    print(result.text, end="")
    if args.verbose:
        print(f"\n--- {result.count} replacement(s) ---", file=sys.stderr)
        for category, value, token in result.replacements:
            print(f"  {category:10} {value!r} -> {token}", file=sys.stderr)
        if not args.no_ner and not ner_available():
            print(
                "  note: spaCy NER not installed — name detection is regex-only.\n"
                "  pip install spacy && python -m spacy download en_core_web_sm",
                file=sys.stderr,
            )
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    vault = TokenVault(args.vault)
    print(restore(_read_input(args.file), vault), end="")
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    vault = TokenVault(args.vault)
    stats = vault.stats()
    if not stats:
        print("vault empty")
        return 0
    for category, count in sorted(stats.items()):
        print(f"{category:12} {count}")
    print(f"{'TOTAL':12} {sum(stats.values())}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .proxy import create_app

    app = create_app(backend_url=args.backend, vault_path=args.vault, use_ner=not args.no_ner)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    from .watch import watch

    vault = TokenVault(args.vault)
    try:
        watch(args.in_dir, args.out_dir, vault, use_ner=not args.no_ner, once=args.once)
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hipaa-bridge", description=__doc__)
    parser.add_argument("--vault", default="hipaa_bridge_vault.db", help="vault DB path")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scrub", help="replace PHI with tokens")
    p.add_argument("file", nargs="?", help="input file (default: stdin)")
    p.add_argument("--no-ner", action="store_true", help="disable spaCy NER layer")
    p.add_argument("-v", "--verbose", action="store_true", help="list replacements on stderr")
    p.set_defaults(func=_cmd_scrub)

    p = sub.add_parser("restore", help="replace tokens with original PHI")
    p.add_argument("file", nargs="?", help="input file (default: stdin)")
    p.set_defaults(func=_cmd_restore)

    p = sub.add_parser("audit", help="summarize vault contents")
    p.set_defaults(func=_cmd_audit)

    p = sub.add_parser("serve", help="run web UI + de-identifying proxy")
    p.add_argument("--backend", default="http://localhost:11434", help="OpenAI-compatible backend base URL (default: local Ollama)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8484)
    p.add_argument("--no-ner", action="store_true")
    p.set_defaults(func=_cmd_serve)

    p = sub.add_parser("watch", help="watch a folder: files in -> scrubbed files out")
    p.add_argument("--in", dest="in_dir", default="in", help="input folder (default: in/)")
    p.add_argument("--out", dest="out_dir", default="out", help="output folder (default: out/)")
    p.add_argument("--no-ner", action="store_true")
    p.add_argument("--once", action="store_true", help="process current files and exit")
    p.set_defaults(func=_cmd_watch)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
