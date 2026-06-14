# HIPAA-Bridge

[![CI](https://github.com/likitha-shankar/hipaa-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/likitha-shankar/hipaa-bridge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Local clinical text de-identification with **reversible, deterministic tokens**. Strip PHI before text leaves your machine; restore it in the response — locally. The token↔value vault never leaves your network.

```
"Patient John Doe (DOB: 11/12/1978) admitted to St. Jude Hospital..."
                          │  scrub (local)
                          ▼
"Patient [PATIENT_88182690] (DOB: [DATE_A804EBEF]) admitted to [FACILITY_3FFBB7A6]..."
                          │  → any LLM (Ollama, Groq, Gemini, ...) →
                          ▼
"Recommend cardiac workup for [PATIENT_88182690]"
                          │  restore (local)
                          ▼
"Recommend cardiac workup for John Doe"
```

**Why reversible?** One-way scrubbers (Philter, NLM Scrubber, Presidio) destroy the link back to the patient. HIPAA-Bridge derives tokens from an HMAC of the value, so the same patient always gets the same token across documents — referential consistency for the model, full re-identification for you, nothing reversible for anyone without your local vault and secret.

## Quick start

```bash
docker compose up                      # bridge at http://localhost:8484
docker compose --profile ai up         # + bundled Ollama: fully local, $0
```

Or pull the pre-built image (published to GHCR on every push to `main`):

```bash
docker run -p 8484:8484 -v hipaa-bridge-data:/data ghcr.io/likitha-shankar/hipaa-bridge:main
```

Or without Docker:

```bash
pip install -e .
hipaa-bridge serve                     # web UI + setup wizard at :8484
```

First visit walks you through a setup wizard: local Ollama, any OpenAI-compatible API URL + key, or scrub-only (no AI).

## Three ways to use it — no coding required

| Mode | Who it's for | How |
|---|---|---|
| **Web UI** | Anyone | `hipaa-bridge serve`, open browser, paste text |
| **Watch folder** | Research/data teams ("honest brokers") | `hipaa-bridge watch` — drop files in `in/`, collect scrubbed copies from `out/` |
| **HTTP endpoints** | Hospital interface engines (Mirth/NextGen Connect) | POST `{"text": ...}` to `/api/scrub` and `/api/restore` from any channel |

Plus a drop-in **OpenAI-compatible proxy** (`/v1/chat/completions`): point your existing app at the bridge instead of the backend; outbound messages are scrubbed, streamed responses restored token-safe across chunk boundaries.

And it pipes:

```bash
cat note.txt | hipaa-bridge scrub | ollama run llama3.2 | hipaa-bridge restore
```

## What gets detected

HIPAA Safe Harbor categories via regex: patient/provider names (labeled), dates, MRNs, SSNs, phone, email, URLs, IPs, ZIP codes, facilities, ages over 89, labeled IDs. Clinical content — drug names, dosages, lab values, symptoms — is never touched.

Optional spaCy NER layer catches unlabeled person/location names in free text:

```bash
pip install spacy && python -m spacy download en_core_web_sm
```

## Important limitations

- **This is not a compliance guarantee.** No automated de-identifier achieves 100% recall on messy clinical text. Use as a PHI-minimization layer (HIPAA minimum-necessary), not a substitute for a BAA or legal review. Expert determination or human review is still required for Safe Harbor claims.
- Benchmarking against the i2b2 2014 de-identification corpus is on the roadmap; until then, treat recall numbers as unverified.
- The vault database and HMAC secret are the keys to re-identification — protect them like PHI.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

MIT licensed.
