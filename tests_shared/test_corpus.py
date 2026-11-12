"""O corpus compartilhado tem de ter os bytes registrados no manifesto (hash dos 20 arquivos)."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "comparacao/avaliacao/manifesto_corpus.json").read_text(encoding="utf-8"))
FILES = {item["arquivo"]: item["sha256"] for item in MANIFEST["arquivos"]}


def test_manifest_points_to_the_shared_corpus_folder():
    assert MANIFEST["corpus"] == "data"
    assert {path.name for path in (ROOT / "data").iterdir() if path.is_file()} == set(FILES)


@pytest.mark.parametrize("name", sorted(FILES))
def test_corpus_file_matches_manifest_hash(name):
    # Conversão de fim de linha (text=auto/autocrlf) já alterou um CSV com finais de linha mistos.
    assert hashlib.sha256((ROOT / "data" / name).read_bytes()).hexdigest() == FILES[name]


def test_corpus_is_stored_without_line_ending_conversion():
    result = subprocess.run(["git", "check-attr", "text", "--", "data/cnae20.csv"], cwd=ROOT,
                            capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("git indisponível")
    assert result.stdout.strip().endswith("text: unset")
