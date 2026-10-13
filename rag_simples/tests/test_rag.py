import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rag import SimpleRAG, split_text


class RAGTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.documents = self.root / "docs"
        self.documents.mkdir()
        self.index = self.root / "index.json"
        self.rag = SimpleRAG(self.index, "fake-embedding", "fake-llm")

    def write_documents(self):
        (self.documents / "biblioteca.md").write_text("Livros: empréstimo por 14 dias.", encoding="utf-8")
        (self.documents / "restaurante.txt").write_text("Almoço servido ao meio-dia.", encoding="utf-8")
        (self.documents / "ignorado.csv").write_text("fora da base", encoding="utf-8")

    def test_index_reload_search_and_grounded_prompt(self):
        self.write_documents()
        self.rag.embed = Mock(return_value=[[10, 0], [0, 3]])
        self.assertEqual(self.rag.index(self.documents), 2)
        # Reabre o índice em outra instância e consulta com vetor não unitário.
        reopened = SimpleRAG(self.index, "fake-embedding", "fake-llm")
        reopened.embed_query = Mock(return_value=[7, 0])
        results = reopened.search("Prazo dos livros?", top_k=1)
        self.assertEqual(results[0]["source"], "biblioteca.md")
        self.assertAlmostEqual(results[0]["score"], 1.0)
        client = Mock()
        client.complete.return_value = SimpleNamespace(text="14 dias [1].")
        reopened._client = client
        self.assertEqual(reopened.answer("Prazo?", results), "14 dias [1].")
        prompt = client.complete.call_args.args[0]
        self.assertIn("[1] Fonte: biblioteca.md", prompt)
        self.assertIn("14 dias", prompt)
        self.assertNotIn("Almoço", prompt)

    def test_failed_reindex_preserves_previous_index(self):
        self.write_documents()
        self.rag.embed = Mock(return_value=[[1, 0], [0, 1]])
        self.rag.index(self.documents)
        previous = self.index.read_bytes()
        self.rag.embed = Mock(side_effect=RuntimeError("API indisponível"))
        with self.assertRaises(RuntimeError):
            self.rag.index(self.documents)
        self.assertEqual(self.index.read_bytes(), previous)

    def test_changed_embedding_model_rejected_before_api(self):
        self.write_documents()
        self.rag.embed = Mock(return_value=[[1, 0], [0, 1]])
        self.rag.index(self.documents)
        self.rag.embedding_model = "outro-modelo"
        self.rag.embed.reset_mock()
        with self.assertRaisesRegex(ValueError, "modelo de embeddings mudou"):
            self.rag.search("Pergunta")
        self.rag.embed.assert_not_called()

    def test_missing_corrupt_and_empty_index(self):
        with self.assertRaisesRegex(ValueError, "Índice não encontrado"):
            self.rag.search("Pergunta")
        for content in ("invalid", json.dumps({"version": 1, "chunks": [], "vectors": []})):
            with patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", return_value=content):
                with self.assertRaisesRegex(ValueError, "Índice inválido"):
                    self.rag.search("Pergunta")
        with self.assertRaisesRegex(ValueError, "Nenhum texto"):
            self.rag.index(self.documents)

    def test_dimension_mismatch_is_not_silently_truncated(self):
        self.write_documents()
        self.rag.embed = Mock(return_value=[[1, 0], [0, 1]])
        self.rag.index(self.documents)
        self.rag.embed_query = Mock(return_value=[1, 0, 0])
        with self.assertRaisesRegex(ValueError, "Dimensão"):
            self.rag.search("Pergunta")

    def test_chunk_overlap_and_argument_validation(self):
        self.assertEqual(split_text("abcdefghij", size=6, overlap=2), ["abcdef", "efghij"])
        for size, overlap in ((0, 0), (10, 10), (10, -1)):
            with self.assertRaises(ValueError):
                split_text("texto", size, overlap)
        with self.assertRaises(ValueError):
            self.rag.search(" ")
        with self.assertRaises(ValueError):
            self.rag.search("Pergunta", top_k=0)


if __name__ == "__main__":
    unittest.main()
