import pytest

from hipaa_bridge.vault import TokenVault


@pytest.fixture
def vault(tmp_path):
    v = TokenVault(tmp_path / "vault.db")
    yield v
    v.close()


def test_roundtrip(vault):
    token = vault.tokenize("PATIENT", "John Doe")
    assert token.startswith("[PATIENT_")
    assert token.endswith("]")
    assert vault.lookup(token) == "John Doe"


def test_deterministic(vault):
    assert vault.tokenize("PATIENT", "John Doe") == vault.tokenize("PATIENT", "John Doe")


def test_whitespace_and_case_normalization(vault):
    t1 = vault.tokenize("PATIENT", "John  Doe")
    t2 = vault.tokenize("PATIENT", "John Doe")
    assert t1 == t2


def test_category_separates_namespaces(vault):
    assert vault.tokenize("PATIENT", "Jordan") != vault.tokenize("PROVIDER", "Jordan")


def test_deterministic_across_instances(tmp_path):
    v1 = TokenVault(tmp_path / "a.db", secret=b"fixed-secret")
    v2 = TokenVault(tmp_path / "b.db", secret=b"fixed-secret")
    assert v1.tokenize("PATIENT", "Jane Roe") == v2.tokenize("PATIENT", "Jane Roe")
    v1.close()
    v2.close()


def test_stats(vault):
    vault.tokenize("PATIENT", "A B")
    vault.tokenize("PATIENT", "C D")
    vault.tokenize("DATE", "01/01/2020")
    assert vault.stats() == {"PATIENT": 2, "DATE": 1}


def test_unknown_token_lookup(vault):
    assert vault.lookup("[PATIENT_DEADBEEF]") is None
