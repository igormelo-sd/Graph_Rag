"""Coleta de desenvolvimento das aplicações principal/GraphRAG e revisão por componentes.

Não substitui o experimento controlado entre implementações em comparacao/run.py.
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DIMENSIONS = ('correcao', 'apoio_documental', 'completude', 'qualificacao')


def application(variant):
    if variant == 'principal': return ROOT, 'RAG Principal'
    if variant == 'graphrag': return ROOT/'graphrag', 'GraphRAG'
    raise ValueError('Escolha principal ou graphrag; a comparação controlada usa seu executor próprio.')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_cases(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def fixed_model(provider, model):
    if provider not in {'openrouter', 'openai', 'ollama'}:
        raise ValueError('Provedor não suportado.')
    value = model.casefold().strip()
    if not value or value in {'openrouter/free', 'openrouter/auto', 'auto'} or 'latest' in value or '*' in value:
        raise ValueError('Informe um modelo específico; roteadores dinâmicos e latest não são reproduzíveis.')


def worksheet(cases):
    return [{'id': c['id'], 'revisao_gabarito': c['revisao_humana'], 'avaliador': None,
             'componentes': {d: {'nota': None, 'justificativa': ''} for d in DIMENSIONS},
             'pontos': [{'ponto': p, 'atendido': None, 'evidencia': ''} for p in c['pontos_obrigatorios']]}
            for c in cases]


def score(rows):
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Revisões vazias ou IDs duplicados.')
    totals = {d: 0 for d in DIMENSIONS}
    omissions = 0
    for row in rows:
        if not row.get('avaliador') or row['revisao_gabarito']['status'] != 'aprovada':
            raise ValueError('Pontuação exige gabarito aprovado e avaliador identificado.')
        if not row.get('pontos'):
            raise ValueError('Revisão sem pontos obrigatórios.')
        for point in row['pontos']:
            if type(point.get('atendido')) is not bool or not point.get('evidencia', '').strip():
                raise ValueError('Revise cada ponto, inclusive omissões, com justificativa/evidência.')
            omissions += not point['atendido']
        for d in DIMENSIONS:
            component = row['componentes'][d]
            if type(component['nota']) is not int or component['nota'] not in (0, 1, 2) or not component['justificativa'].strip():
                raise ValueError('Cada componente exige nota 0–2 e justificativa.')
            totals[d] += component['nota']
    return {'perguntas': len(rows), 'medias_por_componente': {d: totals[d]/len(rows) for d in DIMENSIONS},
            'pontos_omitidos': omissions, 'metodo': 'rubrica_humana_por_componente'}


async def collect(args):
    fixed_model(args.provider, args.model)
    cases = read_cases(HERE / 'desenvolvimento.jsonl')
    if args.ids:
        wanted = set(args.ids.split(','))
        if wanted - {c['id'] for c in cases}: raise ValueError('ID desconhecido.')
        cases = [c for c in cases if c['id'] in wanted]
    if not args.allow_unreviewed and any(c['revisao_humana']['status'] != 'aprovada' for c in cases):
        raise ValueError('Revise os gabaritos ou use --allow-unreviewed para coleta sem pontuação.')
    sys.path.insert(0, str(ROOT))
    variant = getattr(args, 'versao', 'graphrag')
    base_dir, label = application(variant)
    from rag_app.bootstrap import activate
    activate(base_dir)
    from dotenv import load_dotenv
    load_dotenv(base_dir / '.env')
    os.environ['RAG_LLM_PROVIDER'] = args.provider
    os.environ['RAG_LLM_TEMPERATURE'] = '0'
    if args.context_tokens is not None:
        if not 1000 <= args.context_tokens <= 100000: raise ValueError('Contexto deve ter entre 1000 e 100000 tokens estimados.')
        os.environ['RAG_MAX_CONTEXT_TOKENS'] = str(args.context_tokens)
    for key in ('RAG_LLM_MODEL', 'RAG_INTERP_MODEL', 'RAG_POPUP_MODEL'):
        os.environ[key] = args.model
    from startup import initialize
    from query_service import execute_engine_query
    import query_interpreter
    interpreter = getattr(query_interpreter, 'ainterpret_query', query_interpreter.interpret_query)
    from index_manifest import resolve_data_dir
    corpus = Path(resolve_data_dir(str(base_dir)))
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    paths = lambda: sorted(corpus.rglob('*'))
    code = lambda: sorted((base_dir/'src').glob('*.py')) + sorted((ROOT/'rag_app').glob('*.py')) + [Path(__file__)]
    snapshot = lambda ps: {str(p.resolve()): digest(p) for p in ps if p.is_file()}
    manifest = {'created_utc': datetime.now(timezone.utc).isoformat(), 'provider': args.provider,
                'model': args.model, 'python': sys.version, 'dataset_sha256': digest(HERE/'desenvolvimento.jsonl'),
                'corpus': snapshot(paths()), 'code': snapshot(code()), 'ids': [c['id'] for c in cases],
                'scope': f'aplicacao_{variant}_desenvolvimento', 'variant': variant, 'corpus_directory': str(corpus),
                'human_gold_reviewed': not any(c['revisao_humana']['status'] != 'aprovada' for c in cases),
                'environment': {k: v for k,v in os.environ.items() if k.startswith('RAG_') and re_safe_setting(k)},
                'package_versions': {}}
    from importlib.metadata import version, PackageNotFoundError
    for name in ('llama-index-core', 'llama-index-llms-openai', 'llama-index-llms-ollama', 'chromadb', 'pandas', 'openpyxl'):
        try: manifest['package_versions'][name] = version(name)
        except PackageNotFoundError: manifest['package_versions'][name] = None
    if args.provider == 'ollama':
        import urllib.request
        base = os.getenv('RAG_LLM_BASE_URL','http://127.0.0.1:11434/v1').rstrip('/').removesuffix('/v1')
        with urllib.request.urlopen(base+'/api/tags', timeout=10) as response:
            tags = json.load(response)['models']
        entry = next((m for m in tags if m['name'] == args.model), None)
        if not entry or not entry.get('digest'): raise ValueError('Modelo local não encontrado com digest verificável.')
        manifest['local_model_digest'] = entry['digest']
    write(output/'manifesto.json', manifest)
    write(output/'revisao.json', worksheet(cases))
    engine, interp = await asyncio.to_thread(initialize, str(base_dir), data_dir=str(corpus))
    statuses = {}
    for case in cases:
        started = time.perf_counter()
        try:
            # O único conteúdo do gabarito enviado ao aplicativo é a pergunta.
            response, _ = await execute_engine_query(question=case['pergunta'], engine=engine, interp_llm=interp,
                interpreter=interpreter, rag_type=variant, rag_label=label)
            result = {'id': case['id'], 'pergunta': case['pergunta'], 'response': response.model_dump(), 'status': 'ok'}
            reported = response.usage.get('reported_models', [])
            result['model_identity_verified'] = bool(response.usage.get('model_reporting_complete')) and all(m == args.model for m in reported)
            if reported and any(m != args.model for m in reported):
                result['status'] = 'model_identity_mismatch'
        except Exception as exc:
            result = {'id': case['id'], 'status': 'technical_error', 'error_type': type(exc).__name__}
        result['seconds'] = round(time.perf_counter()-started,3)
        write(output/(case['id']+'.json'), result)
        statuses[case['id']] = result['status']
        print(case['id'], result['status'], flush=True)
        # Crédito, limites ou troca de identidade encerram a rodada; não há troca automática.
        if result['status'] != 'ok': break
    manifest['snapshot_unchanged'] = snapshot(paths()) == manifest['corpus'] and snapshot(code()) == manifest['code'] and digest(HERE/'desenvolvimento.jsonl') == manifest['dataset_sha256']
    manifest['statuses'] = statuses
    manifest['collection_complete'] = len(statuses) == len(cases) and all(s == 'ok' for s in statuses.values())
    manifest['finished_utc'] = datetime.now(timezone.utc).isoformat()
    write(output/'manifesto.json', manifest)


def re_safe_setting(key):
    return key in {'RAG_LLM_PROVIDER', 'RAG_LLM_MODEL', 'RAG_INTERP_MODEL', 'RAG_POPUP_MODEL', 'RAG_LLM_TEMPERATURE',
                   'RAG_MAX_OUTPUT_TOKENS', 'RAG_MAX_CONTEXT_TOKENS', 'RAG_BGE_RERANK', 'RAG_GRAPH_STRUCT',
                   'RAG_GRAPH_EMBED', 'RAG_GLOBAL_SEARCH', 'RAG_USE_GRAPH', 'RAG_ENTITY_EXPANSION',
                   'RAG_PARENT_CONTEXT', 'RAG_DEEP_SEARCH', 'RAG_HYDE', 'RAG_EMBED_MODEL', 'RAG_EMBED_PROVIDER'}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('coletar')
    run.add_argument('--provider', required=True)
    run.add_argument('--versao', choices=('principal','graphrag'), default='graphrag')
    run.add_argument('--model', required=True)
    run.add_argument('--output', required=True)
    run.add_argument('--ids')
    run.add_argument('--allow-unreviewed', action='store_true')
    run.add_argument('--context-tokens', type=int, help='Orçamento estimado de evidências (1000–100000); não muda a janela do servidor.')
    review = sub.add_parser('pontuar')
    review.add_argument('arquivo', type=Path)
    args = parser.parse_args()
    if args.command == 'coletar': asyncio.run(collect(args))
    else: print(json.dumps(score(json.loads(args.arquivo.read_text(encoding='utf-8'))), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
