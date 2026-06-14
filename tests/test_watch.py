import pytest

from hipaa_bridge.vault import TokenVault
from hipaa_bridge.watch import watch


@pytest.fixture
def vault(tmp_path):
    v = TokenVault(tmp_path / "vault.db")
    yield v
    v.close()


def test_watch_once_scrubs_files(tmp_path, vault):
    in_dir, out_dir = tmp_path / "in", tmp_path / "out"
    in_dir.mkdir()
    (in_dir / "note.txt").write_text("Patient Jane Roe seen on 03/04/2025. BP 120/80.")
    (in_dir / "image.png").write_bytes(b"\x89PNG")  # non-text: ignored

    processed = watch(in_dir, out_dir, vault, use_ner=False, once=True)

    assert processed == 1
    scrubbed = (out_dir / "note.txt").read_text()
    assert "Jane Roe" not in scrubbed
    assert "03/04/2025" not in scrubbed
    assert "BP 120/80" in scrubbed
    # original moved out of the inbox
    assert not (in_dir / "note.txt").exists()
    assert (in_dir / "processed" / "note.txt").exists()
    assert (in_dir / "image.png").exists()


def test_watch_once_empty_dir(tmp_path, vault):
    assert watch(tmp_path / "in", tmp_path / "out", vault, once=True) == 0
