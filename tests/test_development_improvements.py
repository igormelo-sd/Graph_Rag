import asyncio
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from domain_ontology import query_constraints
from structured_lookup import StructuredLookup
from rag_app.model_output import response_text, InvalidModelResponse
from numerical_validator import validate_numbers
from comparacao.avaliacao.experimento import fixed_model, worksheet, score


def test_lookup_full_csv_and_cache_invalidation(tmp_path):
    path = tmp_path/'municipios.csv'
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['Cod_Ibge','Localidade','Ano','Setor','Valor'])
        writer.writerows([['3500000','Outro',2018,'PIB',10]]*1100)
        writer.writerow(['3500105','Adamantina',2018,'PIB','R$ 1.070.909.946'])
        writer.writerow(['3500105','Adamantina',2019,'PIB',100])
    lookup = StructuredLookup(tmp_path)
    nodes = lookup.retrieve('Qual PIB de Adamantina em 2018?')
    assert len(nodes) == 1
    assert nodes[0].metadata['row'] == 1102
    assert nodes[0].metadata['table_truncated'] is False
    assert '1.070.909.946' in nodes[0].text
    path.write_text('cod_ibge;municipio;drs\n3500105;Adamantina;Marília\n',encoding='utf-8')
    assert 'Marília' in lookup.retrieve('Cadastro IBGE 3500105')[0].text


def test_exact_cnae_and_excel_cells(tmp_path):
    from openpyxl import Workbook
    (tmp_path/'cnae.csv').write_text('cod_classe;denom_classe\n47.32-6;Comércio de lubrificantes\n47.31-8;Combustíveis\n',encoding='utf-8')
    assert len(StructuredLookup(tmp_path).retrieve('Qual classe CNAE 47.32-6?')) == 1
    book=Workbook(); sheet=book.active; sheet.title='Tabela'
    sheet.append(['Ano','PIB']); sheet.append([2018,.023]); sheet['B2'].number_format='0.0%'
    book.save(tmp_path/'pib.xlsx')
    rows=StructuredLookup(tmp_path).retrieve('Qual valor na célula B2 da planilha?')
    assert len(rows)==1 and '2,3%' in rows[0].text
    assert 'B2' in json.loads(rows[0].metadata['cells'])


@pytest.mark.parametrize('question', ['PIB paulista','PIB mensal paulista','Produto interno bruto trimestral paulista'])
def test_pib_series_means_state(question):
    assert query_constraints(question)['dimensions']['region']==['estado_sp']


def test_generic_sao_paulo_stays_ambiguous():
    assert query_constraints('PIB de São Paulo')['ambiguities']
    assert query_constraints('PIB municipal paulista')['dimensions']['region'] != ['estado_sp']


@pytest.mark.parametrize('text', ['User Safety: safe','Assistant Safety: unsafe','A produção foi de alta em dezembro com crescimento. 因此 while the data and these results','Resposta com caractere \ufffd'])
def test_reject_bad_generation(text):
    with pytest.raises(InvalidModelResponse): response_text(SimpleNamespace(text=text))


@pytest.mark.parametrize('text', ['A produção foi de alta em dezembro com crescimento.', 'A fonte cita “the data and these results” em sua descrição de métodos.', '{"sources": ["text"]}', 'A empresa Huawei atua no setor de tecnologia.'])
def test_accept_ordinary_text_and_literal_quotes(text):
    assert response_text(SimpleNamespace(text=text))==text


def test_regeneration_keeps_sources_and_is_bounded(monkeypatch):
    import llm
    from llama_index.llms.openai import OpenAI
    monkeypatch.setenv('RAG_LLM_PROVIDER','openrouter')
    monkeypatch.setenv('OPENROUTER_API_KEY','test-key')
    complete=Mock(side_effect=[SimpleNamespace(text='User Safety: safe'), SimpleNamespace(text='Resposta com fonte.')])
    monkeypatch.setattr(OpenAI,'complete',complete)
    model=llm.make_llm(model='fixed/model')
    assert model.complete('Fonte literal: 2,3%').text=='Resposta com fonte.'
    assert complete.call_count==2
    assert 'Fonte literal: 2,3%' in complete.call_args.args[0]
    assert 'português' in complete.call_args.args[0]


SOURCE='Produção industrial, com ajuste sazonal. Em dezembro de 2025, a produção industrial do Rio de Janeiro registrou avanço de 2,3%, após queda de 1,6% em novembro de 2025.'


def check_answer(answer):
    node=SimpleNamespace(metadata={'type':'text'},get_content=lambda:SOURCE)
    return validate_numbers(answer,[node])


def test_local_numeric_binding():
    checks=check_answer('A produção industrial do Rio de Janeiro avançou 2,3% em dezembro de 2025, com ajuste sazonal.')
    assert next(c for c in checks if c.value=='2,3%').verified


@pytest.mark.parametrize('answer', [
    'A produção industrial da Bahia avançou 2,3% em dezembro de 2025, com ajuste sazonal.',
    'A produção industrial do Rio de Janeiro avançou 2,3% em novembro de 2025, com ajuste sazonal.',
    'A produção industrial do Rio de Janeiro teve queda de 2,3% em dezembro de 2025, com ajuste sazonal.',
    'A produção industrial do Rio de Janeiro caiu 2,3% em dezembro de 2025, com ajuste sazonal.',
    'A produção industrial do Rio de Janeiro avançou 2,3% em dezembro de 2025, sem ajuste sazonal.',
    'A produção industrial do Rio de Janeiro avançou 2,3% em dezembro de 2025, na comparação interanual.',
    'A produção industrial do município do Rio de Janeiro avançou 2,3% em dezembro de 2025, com ajuste sazonal.',
])
def test_numeric_coincidence_is_not_evidence(answer):
    assert not next(c for c in check_answer(answer) if c.value=='2,3%').verified


def test_actual_development_rows():
    corpus=Path(__file__).resolve().parents[1]/'data'
    lookup=StructuredLookup(corpus)
    assert any('lubrificantes' in n.text.casefold() for n in lookup.retrieve('Qual classe CNAE 47.32-6?'))
    assert any('Campinas' in n.text and 'drs' in n.text for n in lookup.retrieve('Qual DRS do município de Campinas?'))
    rows=lookup.retrieve('Qual o PIB de Adamantina em 2018?')
    assert any('1.070.909.946' in n.text and n.metadata['row']==38057 for n in rows)
    assert any(n.metadata.get('retrieval_method')=='structured_catalogue' for n in lookup.retrieve('Quais arquivos de classificação e cadastro territorial existem nas bases?'))
    assert any('1.5906513601490868' in n.text and n.metadata['sheet']=='Tabela 3' for n in lookup.retrieve('Qual valor na célula O105 da aba Tabela 3 da planilha?'))
    rows=lookup.retrieve('Qual foi a variação do PIB paulista no primeiro trimestre de 2026 em relação ao trimestre anterior com ajuste sazonal?')
    assert any(n.metadata['sheet']=='Tabela 3' and n.metadata['row']==105 and 'preliminares' in n.text.casefold() for n in rows)
    assert all('Estado de São Paulo' in n.text for n in rows if n.metadata['sheet'])


@pytest.mark.parametrize('model', ['openrouter/free','openrouter/auto','auto','qwen:latest','*'])
def test_fixed_model_rejects_routers(model):
    with pytest.raises(ValueError): fixed_model('openrouter',model)


def test_review_requires_gold_and_complete_rubric():
    row=worksheet([{'id':'D1','revisao_humana':{'status':'pendente'},'pontos_obrigatorios':['Citar não aditividade']}])[0]
    with pytest.raises(ValueError): score([row])
    row['revisao_gabarito']['status']='aprovada'; row['avaliador']='Revisor'
    row['pontos'][0].update(atendido=False,evidencia='Resposta omite a ressalva.')
    for component in row['componentes'].values(): component.update(nota=1,justificativa='Parcial.')
    result=score([row]); assert result['pontos_omitidos']==1
    assert result['medias_por_componente']['completude']==1


def test_model_identity_reporting_does_not_invent_missing_values():
    from query_usage import usage_scope, tracked_call
    with usage_scope() as usage:
        with tracked_call() as record:
            record(SimpleNamespace(raw={'model':'fixed/model','usage':{'prompt_tokens':10,'completion_tokens':5}}))
        assert usage.snapshot()['reported_models']==['fixed/model']
        assert usage.snapshot()['model_reporting_complete']
        with tracked_call() as record:
            record(SimpleNamespace(text='Sem metadados'))
        assert not usage.snapshot()['model_reporting_complete']


def test_structured_rows_reach_the_synthesis_prompt(tmp_path):
    from analysis_engine import AnalysisEngine
    (tmp_path/'cnae.csv').write_text('cod_classe;denom_classe\n47.32-6;Comércio varejista de lubrificantes\n',encoding='utf-8')
    model=SimpleNamespace(complete=Mock(return_value=SimpleNamespace(text='Classe de comércio varejista de lubrificantes.')))
    empty=SimpleNamespace(retrieve=lambda _:[])
    engine=AnalysisEngine(empty,empty,empty,model,structured_retriever=StructuredLookup(tmp_path))
    result=asyncio.run(engine.answer('Qual classe CNAE 47.32-6?',[], 'Qual classe CNAE 47.32-6?'))
    assert result.nodes and result.nodes[0].metadata['row']==2
    assert 'Comércio varejista de lubrificantes' in model.complete.call_args.args[0]


def test_invalid_source_cells_do_not_break_response():
    from query_service import _source_cells
    assert _source_cells(SimpleNamespace(metadata={'cells':['B2']}))==['B2']
    assert _source_cells(SimpleNamespace(metadata={'cells':'invalido'}))==[]


def test_async_regeneration_and_provider_failures(monkeypatch):
    from unittest.mock import AsyncMock
    from llama_index.llms.openai import OpenAI
    from rag_app.model_output import EmptyModelResponse
    import llm
    monkeypatch.setenv('RAG_LLM_PROVIDER','openai')
    monkeypatch.setenv('OPENAI_API_KEY','test-key')
    model=llm.make_llm(model='gpt-4o-mini')
    method=AsyncMock(side_effect=[SimpleNamespace(text='User Safety: safe'),SimpleNamespace(text='Resposta em português com fontes.')])
    monkeypatch.setattr(OpenAI,'acomplete',method)
    assert asyncio.run(model.acomplete('Fonte literal')) .text=='Resposta em português com fontes.'
    assert method.await_count==2 and 'Fonte literal' in method.call_args.args[0]
    method=AsyncMock(return_value=SimpleNamespace(text=''))
    monkeypatch.setattr(OpenAI,'acomplete',method)
    with pytest.raises(EmptyModelResponse): asyncio.run(model.acomplete('Fonte literal'))
    assert method.await_count==2
    method=AsyncMock(side_effect=RuntimeError('429'))
    monkeypatch.setattr(OpenAI,'acomplete',method)
    with pytest.raises(RuntimeError,match='429'): asyncio.run(model.acomplete('Fonte literal'))
    assert method.await_count==1 and model.max_retries==0


def test_regeneration_with_keyword_prompt(monkeypatch):
    from llama_index.llms.openai import OpenAI
    import llm
    monkeypatch.setenv('RAG_LLM_PROVIDER','openai')
    monkeypatch.setenv('OPENAI_API_KEY','test-key')
    method=Mock(side_effect=[SimpleNamespace(text='User Safety: safe'),SimpleNamespace(text='Resposta com fontes.')])
    monkeypatch.setattr(OpenAI,'complete',method)
    llm.make_llm(model='gpt-4o-mini').complete(prompt='Fonte literal')
    assert 'Fonte literal' in method.call_args.kwargs['prompt']
    assert 'português' in method.call_args.kwargs['prompt']


def test_application_variants_keep_their_own_engines():
    from comparacao.avaliacao.experimento import application,ROOT
    assert application('principal')==(ROOT,'RAG Principal')
    assert application('graphrag')==(ROOT/'graphrag','GraphRAG')
    import analysis_engine
    source=Path(analysis_engine.__file__).read_text(encoding='utf-8')
    assert 'self._global_search' not in source
    assert 'expand_parents' not in source
    assert 'retrieval_paths' in source


def test_evaluation_collects_principal_without_loading_graph_engine(tmp_path,monkeypatch):
    import sys
    import query_service
    from comparacao.avaliacao.experimento import collect,ROOT
    calls=[]
    def initialize(base_dir,**kwargs):
        calls.append((base_dir,kwargs))
        return object(),object()
    monkeypatch.setitem(sys.modules,'startup',SimpleNamespace(initialize=initialize))
    async def execute(**kwargs):
        assert kwargs['rag_type']=='principal'
        assert kwargs['question'] and 'gabarito' not in kwargs
        usage={'reported_models':['gpt-4o-mini'],'model_reporting_complete':True}
        response=SimpleNamespace(usage=usage,model_dump=lambda:{'answer':'Comércio varejista de lubrificantes.','usage':usage})
        return response,None
    monkeypatch.setattr(query_service,'execute_engine_query',execute)
    monkeypatch.setattr('dotenv.load_dotenv',lambda *a,**k:False)
    for key in ('RAG_LLM_PROVIDER','RAG_LLM_MODEL','RAG_INTERP_MODEL','RAG_POPUP_MODEL','RAG_LLM_TEMPERATURE','RAG_MAX_CONTEXT_TOKENS'):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv('RAG_DATA_DIR',str(ROOT/'data'))
    args=SimpleNamespace(provider='openai',model='gpt-4o-mini',versao='principal',ids='D004',allow_unreviewed=True,context_tokens=1000,output=str(tmp_path/'rodada'))
    asyncio.run(collect(args))
    result=json.loads((tmp_path/'rodada'/'manifesto.json').read_text(encoding='utf-8'))
    assert calls[0][0]==str(ROOT)
    assert result['scope']=='aplicacao_principal_desenvolvimento'
    assert result['collection_complete'] and result['snapshot_unchanged']
    assert json.loads((tmp_path/'rodada'/'D004.json').read_text(encoding='utf-8'))['model_identity_verified']
