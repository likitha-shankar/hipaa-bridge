import pytest

from hipaa_bridge.sanitizer import StreamRestorer, restore, scrub
from hipaa_bridge.vault import TokenVault

NOTE = (
    "Patient John Doe (DOB: 11/12/1978) was admitted to St. Jude Hospital "
    "by Dr. Sarah Jenkins on 06/01/2026. He presents with acute chest pain. "
    "Troponin levels are 0.05 ng/mL."
)


@pytest.fixture
def vault(tmp_path):
    v = TokenVault(tmp_path / "vault.db")
    yield v
    v.close()


def test_scrub_removes_phi(vault):
    result = scrub(NOTE, vault, use_ner=False)
    for phi in ("John Doe", "11/12/1978", "St. Jude Hospital", "Sarah Jenkins", "06/01/2026"):
        assert phi not in result.text
    assert "Troponin levels are 0.05 ng/mL" in result.text


def test_scrub_restore_roundtrip(vault):
    result = scrub(NOTE, vault, use_ner=False)
    assert restore(result.text, vault) == NOTE


def test_restore_tolerates_dropped_brackets(vault):
    token = vault.tokenize("PATIENT", "John Doe")
    bare = token.strip("[]")
    assert restore(f"Recommend follow-up for {bare} next week.", vault) == (
        "Recommend follow-up for John Doe next week."
    )


def test_restore_leaves_unknown_tokens(vault):
    text = "Result for [PATIENT_CAFEBABE] pending."
    assert restore(text, vault) == text


def test_stream_restorer_token_split_across_chunks(vault):
    token = vault.tokenize("PATIENT", "John Doe")
    full = f"Plan for {token}: rest."
    mid = len(full) - len(token) // 2 - 3  # split inside the token
    restorer = StreamRestorer(vault)
    out = restorer.feed(full[:mid]) + restorer.feed(full[mid:]) + restorer.flush()
    assert out == "Plan for John Doe: rest."


def test_stream_restorer_many_small_chunks(vault):
    token = vault.tokenize("PROVIDER", "Sarah Jenkins")
    full = f"Reviewed by {token} today. ALL CAPS HEADING stays."
    restorer = StreamRestorer(vault)
    out = "".join(restorer.feed(c) for c in full) + restorer.flush()
    assert out == "Reviewed by Sarah Jenkins today. ALL CAPS HEADING stays."


def test_stream_restorer_plain_text_passthrough(vault):
    restorer = StreamRestorer(vault)
    out = restorer.feed("no tokens here, just text. ") + restorer.flush()
    assert out == "no tokens here, just text. "
