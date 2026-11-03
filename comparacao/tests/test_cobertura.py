import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from comparacao.avaliacao.cobertura import covered


def test_references_are_found_by_page_cell_or_record():
    references = [
        {"arquivo": "caderno.pdf", "tipo": "pdf", "pagina_pdf": 29},
        {"arquivo": "tabelas.xlsx", "tipo": "xlsx", "aba": "Tabela 3", "valor_literal": "1.59", "rotulo_linha": "2026.I"},
        {"arquivo": "cnae.csv", "tipo": "csv", "campos": {"cod": "47.3", "denom": "Combustíveis", "vazio": ""}},
    ]
    items = [
        {"source": "caderno.pdf", "text": "...", "metadata": {"page": 29}},
        {"source": "tabelas.xlsx", "text": "2026.I | 1.59", "metadata": {"page": "Tabela 2"}},
        {"source": "cnae.csv", "text": "cod: 47.3 | denom: Combustíveis", "metadata": {"page": "Planilha"}},
    ]
    assert covered(references, items) == [True, False, True]
