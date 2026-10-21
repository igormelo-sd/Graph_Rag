"""Regressões das falhas reais D007, D016, D017, D019 e D020."""
import asyncio
from contextvars import copy_context
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import llm
import load_control
from rag_app.model_output import EmptyModelResponse
from query_interpreter import interpret_query, ainterpret_query


@pytest.fixture
def factory(monkeypatch):
    monkeypatch.setenv('RAG_LLM_PROVIDER', 'openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setenv('RAG_LLM_CONCURRENCY', '1')
    monkeypatch.delenv('RAG_MAX_OUTPUT_TOKENS', raising=False)
    load_control._semaphore.cache_clear()
    yield llm.make_llm(model='openrouter/free')
    load_control._semaphore.cache_clear()


def test_empty_output_is_retried_once_and_each_attempt_is_recorded(factory, monkeypatch):
    from llama_index.llms.openai import OpenAI
    from query_usage import usage_scope
    complete=Mock(side_effect=[SimpleNamespace(text=''), SimpleNamespace(text='Resposta com evidências.')])
    monkeypatch.setattr(OpenAI, 'complete', complete)
    with usage_scope() as usage:
        assert factory.complete('pergunta').text == 'Resposta com evidências.'
    assert complete.call_count == 2
    assert usage.snapshot()['llm_calls'] == 2
    assert factory.max_tokens == 4096
    assert factory.max_retries == 0


def test_persistently_empty_response_stays_a_provider_failure(factory, monkeypatch):
    from llama_index.llms.openai import OpenAI
    complete=Mock(return_value=SimpleNamespace(text=''))
    monkeypatch.setattr(OpenAI, 'complete', complete)
    with pytest.raises(EmptyModelResponse):
        factory.complete('pergunta')
    assert complete.call_count == 2


def test_provider_error_is_not_retried_or_switched(factory, monkeypatch):
    from llama_index.llms.openai import OpenAI
    complete=Mock(side_effect=RuntimeError('429'))
    monkeypatch.setattr(OpenAI, 'complete', complete)
    with pytest.raises(RuntimeError, match='429'):
        factory.complete('pergunta')
    assert complete.call_count == 1


def test_cancelling_native_async_call_releases_the_only_llm_slot(factory, monkeypatch):
    from llama_index.llms.openai import OpenAI
    started=asyncio.Event()
    calls=[]
    async def complete(self, prompt, **kwargs):
        calls.append(prompt)
        if prompt == 'lenta':
            started.set()
            await asyncio.sleep(60)
        return SimpleNamespace(text='resposta')
    monkeypatch.setattr(OpenAI, 'acomplete', complete)
    async def run():
        task=asyncio.create_task(factory.acomplete('lenta'))
        try:
            await asyncio.wait_for(started.wait(), 2)
        except TimeoutError:
            if task.done():
                task.result()
            task.cancel()
            raise
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await asyncio.wait_for(factory.acomplete('seguinte'), 1)).text == 'resposta'
    asyncio.run(run())
    assert calls == ['lenta','seguinte']


def test_cancelled_query_context_cannot_start_new_sync_calls():
    with load_control.query_scope(60):
        context=copy_context()
    with pytest.raises(TimeoutError, match='encerrada'):
        context.run(load_control.call_timeout, 30)


def test_ambiguous_services_query_needs_no_model_call():
    model=SimpleNamespace(complete=Mock(side_effect=AssertionError('não deve chamar LLM')))
    result=interpret_query('Qual foi o crescimento dos serviços?', model)
    assert result['sources'] == []
    assert result['clarification']['required']
    question=result['clarification']['question']
    for word in ['território','período','segmento','comparação']:
        assert word in question
    model.complete.assert_not_called()
    assert asyncio.run(ainterpret_query('Qual foi o crescimento dos serviços?', model)) == result


def test_specific_source_question_does_not_build_all_community_summaries():
    model=SimpleNamespace(complete=Mock(return_value=SimpleNamespace(text='{"sources":["text","global"],"rewritten_query":"classificação"}')))
    result=interpret_query('Quais fontes do corpus permitem distinguir classificação de atividades e classificação territorial?', model)
    assert 'global' not in result['sources']


def test_oversized_community_summary_is_rewritten_not_truncated(tmp_path, monkeypatch):
    from community_search import CommunitySearch
    monkeypatch.setenv('RAG_COMMUNITY_SUMMARY_CHARS','200')
    model=SimpleNamespace(complete=Mock(side_effect=[SimpleNamespace(text='longo '*60),SimpleNamespace(text='Síntese com fonte [1].')]))
    search=object.__new__(CommunitySearch)
    search.llm=model
    assert search._ask('Resuma','[1] Fonte literal') == 'Síntese com fonte [1].'
    assert model.complete.call_count == 2
    assert 'Fonte literal' in model.complete.call_args.args[0]


def test_persistently_oversized_summary_is_rejected(monkeypatch):
    from community_search import CommunitySearch
    monkeypatch.setenv('RAG_COMMUNITY_SUMMARY_CHARS','200')
    search=object.__new__(CommunitySearch)
    search.llm=SimpleNamespace(complete=Mock(return_value=SimpleNamespace(text='longo '*60)))
    with pytest.raises(ValueError,match='após uma revisão'):
        search._ask('Resuma','[1] Fonte literal')
    assert search.llm.complete.call_count == 2


def test_async_empty_output_retry_is_bounded_and_accounted(factory, monkeypatch):
    from llama_index.llms.openai import OpenAI
    from query_usage import usage_scope
    outputs=iter(['','texto com fonte'])
    async def complete(self, *args, **kwargs):
        return SimpleNamespace(text=next(outputs))
    monkeypatch.setattr(OpenAI,'acomplete',complete)
    async def run():
        with usage_scope() as usage:
            result=await factory.acomplete('pergunta')
            assert result.text == 'texto com fonte'
        assert usage.snapshot()['llm_calls'] == 2
    asyncio.run(run())


def test_service_timeout_does_not_block_next_query(factory, monkeypatch):
    from llama_index.llms.openai import OpenAI
    import query_service
    async def complete(self, prompt, **kwargs):
        if prompt == 'lenta':
            await asyncio.sleep(60)
        return SimpleNamespace(text='Resposta sem valores numéricos.')
    monkeypatch.setattr(OpenAI,'acomplete',complete)
    monkeypatch.setattr(query_service,'request_timeout_seconds',lambda:0.1)
    class Engine:
        async def answer(self, question, **kwargs):
            return (await factory.acomplete(question)).text, []
    async def interpreter(question, model):
        return {'sources':['text'],'rewritten_query':question}
    async def run():
        args=dict(engine=Engine(),interp_llm=factory,interpreter=interpreter,rag_type='test',rag_label='Teste')
        with pytest.raises(TimeoutError):
            await query_service.execute_engine_query(question='lenta',**args)
        response,_=await query_service.execute_engine_query(question='seguinte',**args)
        assert response.answer == 'Resposta sem valores numéricos.'
    asyncio.run(run())


def test_point_rate_query_does_not_extract_an_entire_timeseries():
    from rag_app.query_routing import point_comparison
    question='Qual foi a variação da indústria do Rio de Janeiro entre novembro e dezembro de 2025, com ajuste sazonal?'
    assert point_comparison(question)
    assert not point_comparison('Mostre a evolução mensal da indústria de 2020 a 2025 em um gráfico.')
    model=SimpleNamespace(complete=Mock(return_value=SimpleNamespace(text='{"sources":["text","timeseries"],"rewritten_query":"variação industrial"}')))
    sources=interpret_query(question,model)['sources']
    assert 'tables' in sources and 'timeseries' not in sources


def test_graph_cache_restores_concrete_nodes_and_relations(tmp_path):
    from llama_index.core.graph_stores import SimplePropertyGraphStore
    from llama_index.core.graph_stores.types import ChunkNode, EntityNode, Relation
    from graph_indexing import _save_graph_store, _load_graph_store
    store=SimplePropertyGraphStore()
    chunk=ChunkNode(id_='nó-á',text='Fonte literal em português.')
    entity=EntityNode(name='Indústria',label='Setor')
    store.upsert_nodes([chunk,entity])
    relation=Relation(label='HAS_ENTITY',source_id=chunk.id,target_id=entity.id)
    store.upsert_relations([relation])
    path=str(tmp_path/'grafo.json')
    _save_graph_store(store,path)
    restored=_load_graph_store(path)
    assert isinstance(restored.graph.nodes[chunk.id],ChunkNode)
    assert isinstance(restored.graph.nodes[entity.id],EntityNode)
    assert restored.graph.nodes[chunk.id].text==chunk.text
    assert restored.graph.triplets==store.graph.triplets
    assert set(restored.graph.relations)==set(store.graph.relations)


def test_valid_graph_cache_is_not_rebuilt_or_rewritten(tmp_path, monkeypatch):
    import json
    import graph_indexing as module
    from llama_index.core.graph_stores import SimplePropertyGraphStore
    from llama_index.core.graph_stores.types import EntityNode, Relation
    monkeypatch.setattr(module,'_graph_embed_enabled',lambda:False)
    monkeypatch.setattr(module,'_graph_struct_enabled',lambda:True)
    monkeypatch.setattr(module,'domain_enabled',lambda:True)
    monkeypatch.setattr(module,'fingerprint',lambda:'test-ontology')
    monkeypatch.setattr('graph_ontology.ontology_enabled',lambda:False)
    directory=tmp_path/'graph_store'
    directory.mkdir()
    (directory/'graph_config.json').write_text(json.dumps({'llm':False,'embed':False,'struct':True,'ontology':False,'domain_enabled':True,'ontology_hash':'test-ontology','graph_pipeline':'typed-observations-entity-links-v3'}))
    store=SimplePropertyGraphStore()
    nodes=[EntityNode(name='Fonte'),EntityNode(name='Documento')]
    store.upsert_nodes(nodes)
    store.upsert_relations([Relation(label='PARTE_DE',source_id=nodes[0].id,target_id=nodes[1].id)])
    module._save_graph_store(store,str(directory/'graph_store.json'))
    (directory/'graph_store.png').write_bytes(b'present')
    forbidden=Mock(side_effect=AssertionError('cache válido não deve ser refeito'))
    monkeypatch.setattr(module,'_inject_structural_triplets',forbidden)
    monkeypatch.setattr(module,'_inject_domain_triplets',forbidden)
    monkeypatch.setattr(module,'_save_graph_store',forbidden)
    sentinel=object()
    monkeypatch.setattr(module.PropertyGraphIndex,'from_existing',lambda **kwargs:sentinel)
    assert module.build_or_load_graph([],str(tmp_path),None,use_llm=False) is sentinel
    forbidden.assert_not_called()


def test_sync_retriever_uses_cancellable_client_and_total_call_timeout(factory, monkeypatch):
    from llama_index.llms.openai import OpenAI
    cancelled=asyncio.Event()
    factory.timeout=0.05
    async def complete(self, prompt, **kwargs):
        if prompt == 'lenta':
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()
        return SimpleNamespace(text='Resposta com fonte.')
    monkeypatch.setattr(OpenAI,'acomplete',complete)
    async def run():
        with load_control.query_scope(5):
            with pytest.raises(TimeoutError):
                await asyncio.to_thread(factory.complete,'lenta')
            await asyncio.wait_for(cancelled.wait(),1)
            assert (await factory.acomplete('seguinte')).text == 'Resposta com fonte.'
    asyncio.run(run())


def test_free_router_uses_low_reasoning_effort_but_respects_override(factory, monkeypatch):
    assert factory.additional_kwargs['extra_body']['reasoning']['effort'] == 'low'
    monkeypatch.setenv('RAG_REASONING_EFFORT','medium')
    assert llm.make_llm(model='openrouter/free').additional_kwargs['extra_body']['reasoning']['effort'] == 'medium'


def test_published_point_rate_preserves_literal_table_without_llm_extraction(monkeypatch):
    from llama_index.core.schema import TextNode, NodeWithScore
    from tables_retriever import TablesRetriever
    question='Qual foi a variação da indústria do Rio de Janeiro em dezembro de 2025, com ajuste sazonal?'
    source=NodeWithScore(node=TextNode(text='Rio de Janeiro: 2,3% em dezembro de 2025, com ajuste sazonal.',metadata={'type':'table','source_file':'indústria.pdf','page':15,'table_granularidade':'estática'}))
    monkeypatch.setattr('tables_retriever.filter_candidates',lambda nodes,question:nodes)
    monkeypatch.setattr('tables_retriever._is_static_table',lambda node:True)
    monkeypatch.setattr('rag_selection.pack_context',lambda nodes,question:('Fonte literal: 2,3%',nodes))
    model=SimpleNamespace(complete=Mock(side_effect=AssertionError('Não deve extrair JSON para taxa literal')))
    retriever=TablesRetriever(SimpleNamespace(retrieve=lambda q:[source]),SimpleNamespace(postprocess_nodes=lambda nodes,**kwargs:nodes),model)
    result=retriever.retrieve(question)
    assert result.nodes == [source]
    assert '2,3%' in result.data
    model.complete.assert_not_called()
