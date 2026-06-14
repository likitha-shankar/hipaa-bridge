"""PHI detectors covering the HIPAA Safe Harbor identifier categories.

Regex detectors are always active. spaCy NER (PERSON/GPE/ORG/FAC) is layered
on top when the optional `spacy` dependency and `en_core_web_sm` model are
installed — names in free text are unreliable with regex alone.

Each detector yields Span(start, end, category, value). Overlaps are resolved
by the sanitizer (longest span wins).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    category: str
    value: str


# --- Regex patterns -----------------------------------------------------
# Category names double as token prefixes: [PATIENT_9A4F], [DATE_1B22], ...

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Social Security numbers
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # Medical record numbers — "MRN: 12345678", "MRN #12345678", "Record No. 12345"
    ("MRN", re.compile(r"(?:\bMRN|\bMedical Record(?: Number| No\.?)?)[\s:#]*([A-Z]?\d{5,12})", re.IGNORECASE)),
    # Health plan / account / device-ish long identifiers with explicit labels
    ("ID", re.compile(r"(?:\bMember ID|\bPolicy(?: No\.?| Number)?|\bAccount(?: No\.?| Number)?|\bDevice(?: Serial)?(?: No\.?| Number)?)[\s:#]*([A-Z0-9-]{5,20})", re.IGNORECASE)),
    # US phone numbers
    ("PHONE", re.compile(r"(?<![\w.])(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b")),
    # Fax handled by PHONE pattern; email:
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # URLs and IPs
    ("URL", re.compile(r"\bhttps?://\S+\b")),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    # Dates: 11/12/1978, 11-12-78, 2026-06-01
    ("DATE", re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")),
    # Dates: "October 14, 2025", "Oct 14 2025", "14 October 2025"
    ("DATE", re.compile(
        r"\b(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
        r"|\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{4})\b")),
    # Ages over 89 must be redacted under Safe Harbor
    ("AGE", re.compile(r"\b(9\d|1[0-4]\d)[- ]?(?:years?[- ]old|y/?o)\b", re.IGNORECASE)),
    # ZIP codes with context ("ZIP: 60614", ", IL 60614")
    ("ZIP", re.compile(r"(?:\bZIP(?: Code)?[\s:#]*|,\s*[A-Z]{2}\s+)(\d{5}(?:-\d{4})?)\b", re.IGNORECASE)),
    # Titled clinician names — "Dr. Sarah Jenkins", "Nurse Kelly"
    ("PROVIDER", re.compile(r"\b(?:Dr|Doctor|Nurse|NP|PA|RN)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")),
    # Labeled patient names — "Patient John Doe", "Patient: John Doe", "Pt. Jane A. Smith"
    ("PATIENT", re.compile(r"\b(?:Patient|Pt)\.?:?\s+([A-Z][a-z]+(?:\s+(?:[A-Z]\.?\s+)?[A-Z][a-z]+){1,2})")),
    # Hospitals / facilities — "St. Jude Hospital", "Northwestern Memorial Hospital"
    ("FACILITY", re.compile(r"\b((?:[A-Z][A-Za-z.']+\s+){1,4}(?:Hospital|Medical Center|Clinic|Health(?:care)? (?:System|Center)|Infirmary))\b")),
]

# Group-bearing patterns: replace only the captured group, not the label.
_GROUP_CATEGORIES = {"MRN", "ID", "ZIP", "PROVIDER", "PATIENT"}


def _regex_spans(text: str) -> Iterator[Span]:
    for category, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            if category in _GROUP_CATEGORIES and m.lastindex:
                start, end = m.span(1)
                value = m.group(1)
            else:
                start, end = m.span()
                value = m.group()
            yield Span(start, end, category, value)


# --- Optional spaCy NER layer -------------------------------------------

_NER_LABEL_TO_CATEGORY = {
    "PERSON": "PATIENT",   # without role context, treat unknown persons as patients
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "FAC": "FACILITY",
    "ORG": "FACILITY",
}

_nlp = None
_nlp_load_failed = False


def _get_nlp():
    global _nlp, _nlp_load_failed
    if _nlp is None and not _nlp_load_failed:
        try:
            import spacy

            _nlp = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer"])
        except Exception:
            _nlp_load_failed = True
    return _nlp


def _ner_spans(text: str) -> Iterator[Span]:
    nlp = _get_nlp()
    if nlp is None:
        return
    for ent in nlp(text).ents:
        category = _NER_LABEL_TO_CATEGORY.get(ent.label_)
        if category:
            yield Span(ent.start_char, ent.end_char, category, ent.text)


# --- Public API ----------------------------------------------------------


def detect(text: str, use_ner: bool = True) -> list[Span]:
    """Return non-overlapping PHI spans, longest-match-wins, sorted by start."""
    spans = list(_regex_spans(text))
    if use_ner:
        spans.extend(_ner_spans(text))
    return resolve_overlaps(spans)


def resolve_overlaps(spans: Iterable[Span]) -> list[Span]:
    # Prefer longer spans; regex (listed first) wins ties via stable sort.
    ordered = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
    result: list[Span] = []
    last_end = -1
    for span in ordered:
        if span.start >= last_end:
            result.append(span)
            last_end = span.end
    return result


def ner_available() -> bool:
    return _get_nlp() is not None
