import json
import os
import re
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_text_splitters import RecursiveCharacterTextSplitter
from llama_index.core.node_parser import LangchainNodeParser
from llama_index.core.extractors import TitleExtractor, KeywordExtractor
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.schema import TextNode
from llm import interp_model, llm_concurrency, make_llm, provider_name
from runtime import bounded_int


# Tabelas com até este número de linhas são indexadas como um único chunk.
# Acima disso cada linha vira um chunk independente (série histórica).
# Parametrizável via RAG_SMALL_TABLE_MAX_ROWS (1..100) para tuning por embedding.
SMALL_TABLE_MAX_ROWS = bounded_int("RAG_SMALL_TABLE_MAX_ROWS", 10, 1, 100)

_ENRICH_PROMPT = """\
Analise a tabela abaixo e retorne APENAS um JSON válido, sem blocos markdown, com os campos:

- "descricao": o que a tabela representa (1-2 frases)
- "periodo": intervalo de tempo coberto, se identificável (ex: "2010-2022"), senão ""
- "indicadores": lista com os principais indicadores/métricas presentes (máx. 5)
- "granularidade": nível de detalhe das linhas (ex: "anual por região", "mensal", "por faixa etária")

Tabela:
{table_text}

Exemplo de resposta:
{{"descricao": "Taxa de desemprego por região do Brasil.", "periodo": "2012-2022", "indicadores": ["taxa de desemprego", "região"], "granularidade": "anual por região"}}"""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _markdown_to_df(doc_text: str) -> pd.DataFrame:
    """Extrai o bloco de tabela markdown do texto do documento e converte para DataFrame."""
    lines = [l for l in doc_text.split("\n") if l.strip().startswith("|")]
    if not lines:
        return pd.DataFrame()

    # Remove a linha separadora  (|---|---|)
    lines = [l for l in lines if not re.match(r"^\|\s*[-:]+[\s|:-]*\|?\s*$", l)]

    if len(lines) < 2:
        return pd.DataFrame()

    header = [c.strip() for c in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[1:]:
        values = [v.strip() for v in line.split("|")[1:-1]]
        if len(values) == len(header):
            rows.append(values)

    # Camelot usa cabeçalhos 0,1,...; preservar a primeira linha literal como cabeçalho.
    if rows and all(re.fullmatch(r"\d+", c) for c in header):
        proposed = rows[0]
        if any(not re.fullmatch(r"[-−]?\d+(?:[.,]\d+)*\s*%?", c) for c in proposed if c):
            header, rows = proposed, rows[1:]

    if not header or len(set(header)) != len(header) or any(not c for c in header):
        # Cabeçalho mesclado/duplicado não pode ser convertido para dict sem perder células.
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=header)


def llm_ingest_enrichment_enabled() -> bool:
    """Define se a indexação deve chamar o LLM para gerar metadados.

    Modelos locais são desativados por padrão: centenas de chamadas seriais
    tornam a primeira indexação muito lenta e um único timeout pode inutilizar
    todo o lote. O enriquecimento continua disponível por configuração.
    """
    raw = os.getenv("RAG_INGEST_LLM_ENRICHMENT")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return provider_name() != "ollama"


def _detect_section_title(text: str) -> str:
    """Heurística determinística (port do kg structural_extractor) para seção.

    Procura nas 3 primeiras linhas não vazias um título curto em maiúsculas
    ou padrão '1. Introdução', 'I. ', etc. Retorna '' se não houver.
    """
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    for line in lines[:3]:
        if 5 <= len(line) <= 90 and len(line.split()) <= 10:
            # numeração + título
            if re.match(r"^\s*(\d+(\.\d+)*|[IVX]+)[\.\-\)]\s+.+", line):
                return line.strip()
            # maiúsculas >60% (título de seção)
            letters = [c for c in line if c.isalpha()]
            if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.6:
                return line.strip()
            # título curto title-case com palavras-chave econômicas
            if re.search(r"\b(introdução|panorama|conjuntura|mercado de trabalho|indústria|comércio|serviços|agropecuária|inflação|PIB|emprego|resultados|considerações)\b", line, re.IGNORECASE) and len(line) <= 60:
                return line.strip()
    return ""


def _infer_table_metadata(table_doc) -> dict:
    """Gera metadados úteis sem rede, usados como padrão/fallback."""
    df = _markdown_to_df(table_doc.text)
    columns = [str(column).strip() for column in df.columns if str(column).strip()][:5]
    source = str(table_doc.metadata.get("source_file") or "tabela")
    description = f"Tabela de {source}"
    if columns:
        description += f" com {', '.join(columns)}"

    text = table_doc.text.lower()
    years = sorted({int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", text)})
    if re.search(r"\b(?:jan(?:eiro)?|fev(?:ereiro)?|mar(?:ço)?|abr(?:il)?|mai(?:o)?|jun(?:ho)?|jul(?:ho)?|ago(?:sto)?|set(?:embro)?|out(?:ubro)?|nov(?:embro)?|dez(?:embro)?)\b", text):
        granularity = "mensal"
    elif re.search(r"\b[1-4](?:º|°|o)?\s*(?:tri|trim|trimestre)\b", text):
        granularity = "trimestral"
    elif len(years) >= 2:
        granularity = "anual"
    else:
        granularity = ""

    if len(years) >= 2:
        period = f"{years[0]}-{years[-1]}"
    elif years:
        period = str(years[0])
    else:
        period = ""

    return {
        "table_descricao": description,
        "table_periodo": period,
        "table_indicadores": ", ".join(columns),
        "table_granularidade": granularity,
    }


# ---------------------------------------------------------------------------
# Enriquecimento de metadados via LLM
# ---------------------------------------------------------------------------

def _enrich_table_metadata(table_doc, llm) -> dict:
    """
    Chama o LLM uma vez por tabela para gerar metadados semânticos.
    O resultado é propagado para todos os chunks derivados dessa tabela.
    """
    fallback = _infer_table_metadata(table_doc)
    if llm is None:
        return fallback

    try:
        prompt = _ENRICH_PROMPT.format(table_text=table_doc.text[:3000])
        response = llm.complete(prompt)
        enriched = json.loads(response.text)
        return {
            "table_descricao":     enriched.get("descricao") or fallback["table_descricao"],
            "table_periodo":       enriched.get("periodo") or fallback["table_periodo"],
            "table_indicadores":   ", ".join(enriched.get("indicadores", [])) or fallback["table_indicadores"],
            "table_granularidade": enriched.get("granularidade") or fallback["table_granularidade"],
        }
    except Exception as e:
        source = table_doc.metadata.get("source_file", "?")
        print(f"  Aviso: enriquecimento de metadados falhou para {source} — ({e})")
        return fallback


# ---------------------------------------------------------------------------
# Chunking de tabelas
# ---------------------------------------------------------------------------

def _row_to_structured_text(row: dict, source_file: str) -> str:
    """Converte uma linha de DataFrame para texto estruturado (abordagem 3)."""
    lines = [f"{col}: {val}" for col, val in row.items() if str(val).strip()]
    lines.append(f"Fonte: {source_file}")
    return "\n".join(lines)


def _chunk_table(table_doc, extra_metadata: dict | None = None) -> list:
    """
    Estratégia de chunking para tabelas:

    Abordagem 1 — tabela inteira (tabelas pequenas, <= SMALL_TABLE_MAX_ROWS linhas)
        Gera 1 chunk com todas as linhas em texto estruturado.

    Abordagem 2/3 — linha como documento (séries históricas)
        Gera 1 chunk por linha em texto estruturado.

    O formato de saída é sempre texto estruturado (abordagem 3):
        Coluna1: valor1
        Coluna2: valor2
        Fonte: arquivo.pdf
    """
    df = _markdown_to_df(table_doc.text)
    if df.empty:
        return [TextNode(text=table_doc.text, metadata=table_doc.metadata)]

    source    = table_doc.metadata.get("source_file", "")
    base_meta = {**table_doc.metadata, **(extra_metadata or {})}
    nodes     = []
    from document_context import structure_payload, table_identity
    base_meta.setdefault("table_key", table_identity(base_meta, table_doc.text))
    title = base_meta.get("table_title", "")
    notes = json.loads(base_meta.get("table_notes", "[]"))

    def structured_metadata(frame, indices):
        return {**base_meta, "table_structure": structure_payload(
            list(frame.columns), frame.astype(str).values.tolist(), base_meta, title, notes, indices)}

    if len(df) <= SMALL_TABLE_MAX_ROWS:
        # Abordagem 1: tabela inteira como texto estruturado
        rows_text = "\n---\n".join(
            _row_to_structured_text(row.to_dict(), source)
            for _, row in df.iterrows()
        )
        nodes.append(TextNode(
            text=rows_text,
            metadata={**structured_metadata(df, list(range(len(df)))), "chunk_strategy": "full_table"},
        ))
    else:
        # Abordagem 2/3: uma linha por chunk
        for row_index, row in df.iterrows():
            text = _row_to_structured_text(row.to_dict(), source)
            if text.strip():
                nodes.append(TextNode(
                    text=text,
                    metadata={**structured_metadata(df.loc[[row_index]], [int(row_index)]), "chunk_strategy": "row_per_chunk"},
                ))

    return nodes


# ---------------------------------------------------------------------------
# Pipeline de texto
# ---------------------------------------------------------------------------

def _get_text_pipeline(
    llm=None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    enrich_metadata: bool | None = None,
):
    # Parametrizável via env para tuning do embedding local (bge-m3 512-768 tok ≈ 2000-3000 chars)
    if chunk_size is None:
        chunk_size = bounded_int("RAG_CHUNK_SIZE", 1024, 256, 8192)
    if chunk_overlap is None:
        chunk_overlap = bounded_int("RAG_CHUNK_OVERLAP", 200, 0, 1024)
    splitter = LangchainNodeParser(
        RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=min(chunk_overlap, max(chunk_size - 1, 0)),
            # Títulos, parágrafos e frases precedem cortes dentro de palavras.
            separators=[r"\n(?=#{1,6}\s)", r"\n\n+", r"\n", r"(?<=[.!?])\s+(?=[A-ZÀ-Ú])", r"\s+", ""],
            is_separator_regex=True,
            keep_separator=True,
        )
    )
    transformations = [splitter]
    if enrich_metadata is None:
        enrich_metadata = llm_ingest_enrichment_enabled()
    if enrich_metadata:
        if llm is None:
            raise ValueError("llm é obrigatório quando o enriquecimento está ativado")
        workers = llm_concurrency()
        transformations.extend([
            # Passe o provedor configurado explicitamente. Sem isso, os extractors
            # recorrem ao LLM global do LlamaIndex, cujo default é a OpenAI.
            # Falhas de metadados não devem descartar os nós já processados.
            TitleExtractor(
                llm=llm,
                nodes=5,
                num_workers=workers,
                raise_on_error=False,
            ),
            KeywordExtractor(
                llm=llm,
                keywords=5,
                num_workers=workers,
                raise_on_error=False,
            ),
        ])
    return IngestionPipeline(transformations=transformations)


def _assign_deterministic_ids(nodes: list) -> list:
    """Atribui IDs determinísticos (sha256) a cada nó para idempotência em full rebuilds."""
    import hashlib
    for n in nodes:
        md = getattr(n, "metadata", {}) or {}
        source = str(md.get("source_file") or "")
        page = str(md.get("page") or "")
        ntype = str(md.get("type") or "text")
        cid = str(md.get("chunk_id") or "1")
        content = getattr(n, "text", "") or ""
        raw = f"{source}::{page}::{ntype}::{cid}::{content}"
        h = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:32]
        n.id_ = h
        md["node_id"] = h
    return nodes

def process_documents(documents):
    """
    Processa documentos em três caminhos:
    - Texto  → RecursiveCharacterTextSplitter + TitleExtractor + KeywordExtractor
    - Tabela → chunking determinístico em texto estruturado (abordagem 1 ou 2/3)
    - Imagem → 1 node por gráfico (sem splitter, OCR já em texto)
    """
    text_docs  = [d for d in documents if d.metadata.get("type") == "text"]
    table_docs = [d for d in documents if d.metadata.get("type") == "table"]
    image_docs = [d for d in documents if d.metadata.get("type") == "image"]
    use_llm_enrichment = llm_ingest_enrichment_enabled()
    llm = (
        make_llm(interp=True, temperature=0.0, timeout=30.0)
        if use_llm_enrichment and (text_docs or table_docs)
        else None
    )

    print(f"  {len(text_docs)} documento(s) de texto | {len(table_docs)} tabela(s) | {len(image_docs)} imagem(ns)")

    # P0: section determinística por documento antes do split (port kg structural_extractor)
    for d in text_docs:
        sec = _detect_section_title(d.text)
        if sec:
            d.metadata["section"] = sec
        # garante chaves de proveniência mínimas
        d.metadata.setdefault("section", sec)

    # --- Texto ---
    text_nodes = []
    if text_docs:
        mode = "com metadados via LLM" if use_llm_enrichment else "sem chamadas ao LLM"
        print(f"  Processando documentos de texto ({mode})...")
        text_nodes = _get_text_pipeline(
            llm,
            enrich_metadata=use_llm_enrichment,
        ).run(documents=text_docs)
        # Proveniência: chunk_id sequencial por (source_file, page) para grafo 2º embedding
        # + preserva deterministicamente section herdada do doc pai quando pipeline não propagou
        from collections import defaultdict
        _page_counter: dict[tuple, int] = defaultdict(int)
        _page_total: dict[tuple, int] = defaultdict(int)
        for n in text_nodes:
            key = (str(n.metadata.get("source_file") or ""), str(n.metadata.get("page") or ""))
            _page_total[key] += 1
        # Pré-computa mapa (source_file, page) → section para propagar em O(1)
        _section_map: dict[tuple, str] = {
            (str(d.metadata.get("source_file")), str(d.metadata.get("page"))): d.metadata["section"]
            for d in text_docs
            if d.metadata.get("section")
        }
        for n in text_nodes:
            key = (str(n.metadata.get("source_file") or ""), str(n.metadata.get("page") or ""))
            _page_counter[key] += 1
            n.metadata["chunk_id"] = _page_counter[key]
            n.metadata["total_chunks_page"] = _page_total[key]
            if not n.metadata.get("section") and key in _section_map:
                n.metadata["section"] = _section_map[key]

    # --- Tabelas ---
    table_nodes = []
    if table_docs:
        if use_llm_enrichment:
            print(f"  Enriquecendo metadados e aplicando chunking nas tabelas ({interp_model()})...")
        else:
            print("  Inferindo metadados e aplicando chunking nas tabelas (modo local)...")

        enriched: dict[int, dict] = {}
        if llm is None:
            enriched = {
                i: _enrich_table_metadata(doc, None)
                for i, doc in enumerate(table_docs)
            }
        else:
            # Paraleliza as chamadas LLM de enriquecimento (I/O-bound).
            max_workers = min(llm_concurrency(default=8), len(table_docs))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_enrich_table_metadata, doc, llm): i
                           for i, doc in enumerate(table_docs)}
                for fut in as_completed(futures):
                    enriched[futures[fut]] = fut.result()

        for i, doc in enumerate(table_docs):
            extra_meta = enriched[i]
            nodes      = _chunk_table(doc, extra_metadata=extra_meta)
            table_nodes.extend(nodes)
            strategy  = nodes[0].metadata.get("chunk_strategy", "?") if nodes else "?"
            source    = doc.metadata.get("source_file", "?")
            page      = doc.metadata.get("page", "?")
            descricao = extra_meta.get("table_descricao", "")
            print(f"    {source} p.{page} -> {len(nodes)} chunk(s) [{strategy}] | {descricao[:60]}")
        # Proveniência tabelas: chunk_id por página
        if table_nodes:
            from collections import defaultdict as _dd2
            _tc: dict = _dd2(int)
            _tt: dict = _dd2(int)
            for n in table_nodes:
                k = (str(n.metadata.get("source_file") or ""), str(n.metadata.get("page") or ""))
                _tt[k] += 1
            for n in table_nodes:
                k = (str(n.metadata.get("source_file") or ""), str(n.metadata.get("page") or ""))
                _tc[k] += 1
                n.metadata["chunk_id"] = _tc[k]
                n.metadata["total_chunks_page"] = _tt[k]

    # --- Imagens (gráficos rasterizados) ---
    image_nodes = []
    if image_docs:
        print(f"  Processando {len(image_docs)} gráfico(s) extraído(s) via visão (sem splitter)...")
        for doc in image_docs:
            node = TextNode(text=doc.text, metadata=dict(doc.metadata))
            node.metadata["chunk_strategy"] = "image_single"
            image_nodes.append(node)
        if image_nodes:
            from collections import defaultdict as _dd3
            _ic: dict = _dd3(int)
            _it: dict = _dd3(int)
            for n in image_nodes:
                k = (str(n.metadata.get("source_file") or ""), str(n.metadata.get("page") or ""))
                _it[k] += 1
            for n in image_nodes:
                k = (str(n.metadata.get("source_file") or ""), str(n.metadata.get("page") or ""))
                _ic[k] += 1
                n.metadata["chunk_id"] = _ic[k]
                n.metadata["total_chunks_page"] = _it[k]

    all_nodes = text_nodes + table_nodes + image_nodes
    all_nodes = _assign_deterministic_ids(all_nodes)
    from domain_ontology import annotate_node
    for node in all_nodes:
        annotate_node(node)
        node.excluded_embed_metadata_keys = list(dict.fromkeys(node.excluded_embed_metadata_keys + ["table_structure", "table_notes"]))
        node.excluded_llm_metadata_keys = list(dict.fromkeys(node.excluded_llm_metadata_keys + ["table_structure", "table_notes"]))
    print(
        f"Normalização concluída. "
        f"{len(text_nodes)} nós de texto + {len(table_nodes)} nós de tabela + {len(image_nodes)} nós de imagem = {len(all_nodes)} total."
    )
    return all_nodes
