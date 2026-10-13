import pytest
from ollama_embeddings import CachedOllamaEmbedding


def model(tmp_path, digest='revision-a'):
    return CachedOllamaEmbedding(model_name='embeddinggemma:300m', model_digest=digest,
                                cache_path=str(tmp_path/'vectors.sqlite3'), embed_batch_size=2)


def fake_service(monkeypatch):
    calls = []
    def request(url, path, payload):
        calls.append(payload)
        return {'embeddings': [[1., len(t)+1.] for t in payload['input']]}
    monkeypatch.setattr('ollama_embeddings.ollama_request', request)
    return calls


def test_cache_survives_new_instance_and_separates_query_revision(tmp_path, monkeypatch):
    calls = fake_service(monkeypatch)
    first = model(tmp_path).get_text_embedding_batch(['PIB', 'PIB', 'Indústria'])
    assert len(calls) == 2 and sum(len(c['input']) for c in calls) == 2
    second = model(tmp_path).get_text_embedding_batch(['PIB', 'PIB', 'Indústria'])
    assert [x for v in first for x in v] == pytest.approx([x for v in second for x in v])
    assert len(calls) == 2
    model(tmp_path).get_query_embedding('PIB')
    assert calls[-1]['input'][0].startswith('task: search result | query: ')
    model(tmp_path, 'revision-b').get_text_embedding('PIB')
    assert len(calls) == 4


def test_long_text_is_preserved_and_not_truncated(tmp_path, monkeypatch):
    calls = fake_service(monkeypatch)
    text = 'A'*5100
    vector = model(tmp_path).get_text_embedding(text)
    pieces = [t.removeprefix('title: none | text: ') for c in calls for t in c['input']]
    assert ''.join(pieces) == text
    assert all(c['truncate'] is False for c in calls)
    assert sum(v*v for v in vector) == pytest.approx(1.)


def test_completed_batches_are_kept_after_failure(tmp_path, monkeypatch):
    calls = fake_service(monkeypatch)
    m = model(tmp_path)
    original = m._request_vectors
    def failing(texts, query):
        if 'FAIL' in texts:
            raise RuntimeError('server unavailable')
        return original(texts, query)
    monkeypatch.setattr(CachedOllamaEmbedding, '_request_vectors', lambda self, texts, query: failing(texts, query))
    with pytest.raises(RuntimeError, match='server unavailable'):
        m.get_text_embedding_batch(['one', 'two', 'FAIL'])
    before = len(calls)
    assert len(model(tmp_path).get_text_embedding_batch(['one', 'two'])) == 2
    assert len(calls) == before


def test_token_overflow_splits_without_losing_text(tmp_path, monkeypatch):
    accepted = []
    def request(url, path, payload):
        texts = [t.removeprefix('title: none | text: ') for t in payload['input']]
        if any(len(t)>4 for t in texts):
            raise RuntimeError('Ollama HTTP 400: input length exceeds context length')
        accepted.extend(texts)
        return {'embeddings': [[1., 2.] for _ in texts]}
    monkeypatch.setattr('ollama_embeddings.ollama_request', request)
    model(tmp_path).get_text_embedding('abcdefghijk')
    assert ''.join(accepted) == 'abcdefghijk'


def test_processing_checkpoint_validates_corpus(tmp_path, monkeypatch):
    from unittest.mock import Mock
    import index_sync
    read = Mock(return_value=['document'])
    process = Mock(return_value=['node'])
    monkeypatch.setattr(index_sync, 'load_documents', read)
    monkeypatch.setattr(index_sync, 'process_documents', process)
    snapshot = {'__pipeline': 'v1', 'data.csv': {'mtime': 1}}
    db = str(tmp_path/'chroma_db')
    assert index_sync._full_build_nodes('data', db, snapshot, Mock()) == ['node']
    assert index_sync._full_build_nodes('data', db, snapshot, Mock()) == ['node']
    assert process.call_count == 1
    index_sync._full_build_nodes('data', db, {**snapshot, '__pipeline': 'v2'}, Mock())
    assert process.call_count == 2


def test_chroma_rebuild_reuses_cached_vectors(tmp_path, monkeypatch):
    import chromadb
    import indexing
    from llama_index.core.schema import TextNode
    monkeypatch.setenv('RAG_EMBED_MODEL_REVISION', '')
    monkeypatch.setenv('RAG_EMBED_PROVIDER', 'ollama')
    monkeypatch.setenv('RAG_EMBED_MODEL', 'embeddinggemma:300m')
    monkeypatch.setenv('RAG_EMBED_CACHE_PATH', str(tmp_path/'embedding_cache.sqlite3'))
    monkeypatch.setenv('RAG_FAISS', '0')
    monkeypatch.setattr(indexing, '_EMBED_INSTANCE', None)
    monkeypatch.setattr(indexing, '_EMBED_IDENTITY', None)
    calls = []
    def request(url, path, payload=None):
        if path == '/api/tags':
            return {'models': [{'name': 'embeddinggemma:300m', 'digest': 'test-revision'}]}
        calls.append(payload)
        return {'embeddings': [[1., len(t)+1.] for t in payload['input']]}
    monkeypatch.setattr('ollama_embeddings.ollama_request', request)
    nodes = [TextNode(text='PIB paulista', id_='node-a'),
             TextNode(text='Producao industrial brasileira', id_='node-b')]
    db = str(tmp_path/'chroma_db')
    indexing.create_or_load_index(nodes, db_path=db)
    count = len(calls)
    indexing.create_or_load_index(nodes, db_path=db)
    assert len(calls) == count
    assert chromadb.PersistentClient(path=db).get_collection('estatisticas').count() == 2
    assert len(indexing.load_nodes_cache(db)) == 2


def test_provider_and_revision_invalidate_manifest(monkeypatch):
    from index_manifest import _pipeline_fingerprint
    monkeypatch.setenv('RAG_EMBED_PROVIDER', 'ollama')
    monkeypatch.setenv('RAG_EMBED_MODEL_REVISION', 'rev-a')
    first = _pipeline_fingerprint()
    monkeypatch.setenv('RAG_EMBED_MODEL_REVISION', 'rev-b')
    assert first != _pipeline_fingerprint()
    monkeypatch.setenv('RAG_EMBED_PROVIDER', 'huggingface')
    assert first != _pipeline_fingerprint()
