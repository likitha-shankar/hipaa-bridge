from hipaa_bridge.detectors import detect, resolve_overlaps, Span

NOTE = (
    "Patient John Doe (DOB: 11/12/1978) was admitted to St. Jude Hospital "
    "by Dr. Sarah Jenkins on 06/01/2026. MRN: 84421953. "
    "Contact: (312) 555-0148, jdoe@example.com. SSN 321-54-9876. "
    "He presents with acute chest pain. Troponin levels are 0.05 ng/mL."
)


def _categories(text, **kw):
    return {s.category for s in detect(text, use_ner=False, **kw)}


def test_core_identifiers_detected():
    cats = _categories(NOTE)
    assert {"PATIENT", "DATE", "FACILITY", "PROVIDER", "MRN", "PHONE", "EMAIL", "SSN"} <= cats


def test_clinical_values_untouched():
    spans = detect(NOTE, use_ner=False)
    covered = [NOTE[s.start:s.end] for s in spans]
    assert all("Troponin" not in c and "0.05" not in c and "chest pain" not in c for c in covered)


def test_patient_name_value():
    spans = {s.category: s.value for s in detect(NOTE, use_ner=False)}
    assert spans["PATIENT"] == "John Doe"
    assert spans["PROVIDER"] == "Sarah Jenkins"
    assert spans["MRN"] == "84421953"


def test_written_date():
    spans = detect("Discharged on October 14, 2025 in stable condition.", use_ner=False)
    assert len(spans) == 1
    assert spans[0].category == "DATE"
    assert spans[0].value == "October 14, 2025"


def test_age_over_89():
    spans = detect("Patient is a 92-year-old male.", use_ner=False)
    assert any(s.category == "AGE" for s in spans)


def test_age_under_90_kept():
    spans = detect("Patient is a 47-year-old male.", use_ner=False)
    assert not any(s.category == "AGE" for s in spans)


def test_zip_with_context():
    spans = detect("Address on file: Chicago, IL 60614.", use_ner=False)
    assert any(s.category == "ZIP" and s.value == "60614" for s in spans)


def test_overlap_resolution_longest_wins():
    spans = [
        Span(0, 5, "A", "xxxxx"),
        Span(0, 10, "B", "xxxxxxxxxx"),
        Span(12, 15, "C", "yyy"),
    ]
    resolved = resolve_overlaps(spans)
    assert [(s.start, s.end) for s in resolved] == [(0, 10), (12, 15)]
