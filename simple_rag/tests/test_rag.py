import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from simple_rag.rag import Chunk, SimpleRAG


def chunks():
    return [Chunk("Livros: empréstimo por 14 dias.", "biblioteca.md", None, 1, {"node_id": "a"}),
            Chunk("Almoço servido ao meio-dia.", "restaurante.txt", 2, 1, {"node_id": "b"})]


class RAGTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.index = Path(self.temp.name) / "index.json"
        self.rag = SimpleRAG(self.index, "fake-embedding", "fake-llm")

    def test_index_reload_search_and_grounded_prompt(self):
        self.rag.embed = Mock(return_value=[[10, 0], [0, 3]])
        self.assertEqual(self.rag.index_chunks(chunks()), 2)
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
        self.rag.embed = Mock(return_value=[[1, 0], [0, 1]])
        self.rag.index_chunks(chunks())
        previous = self.index.read_bytes()
        self.rag.embed = Mock(side_effect=RuntimeError("API indisponível"))
        with self.assertRaises(RuntimeError):
            self.rag.index_chunks(chunks())
        self.assertEqual(self.index.read_bytes(), previous)

    def test_inconsistent_embeddings_are_rejected_before_writing(self):
        self.rag.embed = Mock(return_value=[[1, 0]])  # um vetor para dois trechos
        with self.assertRaisesRegex(ValueError, "incompatíveis"):
            self.rag.index_chunks(chunks())
        self.assertFalse(self.index.exists())

    def test_changed_embedding_model_rejected_before_api(self):
        self.rag.embed = Mock(return_value=[[1, 0], [0, 1]])
        self.rag.index_chunks(chunks())
        self.rag.embedding_model = "outro-modelo"
        self.rag.embed.reset_mock()
        with self.assertRaisesRegex(ValueError, "modelo de embeddings mudou"):
            self.rag.search("Pergunta")
        self.rag.embed.assert_not_called()

    def test_missing_and_corrupt_index(self):
        with self.assertRaisesRegex(ValueError, "Índice não encontrado"):
            self.rag.search("Pergunta")
        for content in ("invalid", json.dumps({"version": 1, "chunks": [], "vectors": []})):
            with patch.object(Path, "is_file", return_value=True), patch.object(Path, "read_text", return_value=content):
                with self.assertRaisesRegex(ValueError, "Índice inválido"):
                    self.rag.search("Pergunta")

    def test_dimension_mismatch_is_not_silently_truncated(self):
        self.rag.embed = Mock(return_value=[[1, 0], [0, 1]])
        self.rag.index_chunks(chunks())
        self.rag.embed_query = Mock(return_value=[1, 0, 0])
        with self.assertRaisesRegex(ValueError, "Dimensão"):
            self.rag.search("Pergunta")

    def test_argument_validation_and_empty_context(self):
        with self.assertRaises(ValueError):
            self.rag.search(" ")
        with self.assertRaises(ValueError):
            self.rag.search("Pergunta", top_k=0)
        self.assertIn("Não há trechos", self.rag.answer("Pergunta", []))

    def test_embedding_text_can_differ_from_stored_text_and_queries_are_embedded_once(self):
        captured = []
        self.rag.embed = Mock(side_effect=lambda texts: captured.extend(texts) or [[1, 0], [0, 1]])
        self.rag.index_chunks(chunks(), texts=["Documento: a | Livros: empréstimo por 14 dias.", "Documento: b | Almoço."])
        self.assertTrue(captured[0].startswith("Documento: a |"))
        stored = json.loads(self.index.read_text(encoding="utf-8"))
        self.assertEqual(stored["chunks"][0]["text"], "Livros: empréstimo por 14 dias.")  # o contexto mostra o texto original
        with self.assertRaisesRegex(ValueError, "Um texto de embedding por trecho"):
            self.rag.index_chunks(chunks(), texts=["só um"])
        self.rag._embedder = SimpleNamespace(get_query_embedding=Mock(return_value=[1, 0]))
        payload = self.rag.load_index()
        self.rag.search("Pergunta?", 1, payload)
        self.rag.search("Pergunta?", 1, payload, subset=[1])
        self.rag._embedder.get_query_embedding.assert_called_once_with("Pergunta?")
        self.assertEqual(self.rag.search("Pergunta?", 1, payload, subset=[])[:1], [])


if __name__ == "__main__":
    unittest.main()
