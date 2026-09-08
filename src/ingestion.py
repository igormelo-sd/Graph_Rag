import os
import json
import uuid
from pathlib import Path
from datetime import datetime

# Adiciona Ghostscript e Tesseract ao PATH (Windows) para Camelot e OCR
_GS_BIN = r"C:\Program Files\gs\gs10.06.0\bin"
if _GS_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _GS_BIN + os.pathsep + os.environ.get("PATH", "")
_TESS_BIN = r"C:\Program Files\Tesseract-OCR"
if _TESS_BIN not in os.environ.get("PATH", "") and os.path.exists(_TESS_BIN):
    os.environ["PATH"] = _TESS_BIN + os.pathsep + os.environ.get("PATH", "")
os.environ.setdefault("TESSDATA_PREFIX", r"C:\Program Files\Tesseract-OCR\tessdata")

import fitz  # pymupdf
import camelot
import pandas as pd
from llama_index.core import Document

SUPPORTED_EXTS = {'.pdf', '.csv', '.xlsx', '.xls', '.txt'}

# Visão — RAG_VISION=1 ativa pipeline multimodal local (qwen2.5vl:7b via Ollama + fallback tesseract)
# P1: mantém local — sem exfiltração para OpenAI
def _vision_enabled() -> bool:
    return os.getenv("RAG_VISION", "0").strip().lower() in {"1", "true", "yes", "on"}


def _vision_model() -> str:
    return os.getenv("RAG_VISION_MODEL", "qwen2.5vl:7b").strip() or "qwen2.5vl:7b"


def _vision_base_url() -> str:
    # Docker: host.docker.internal ; local: 127.0.0.1 — sobrescreva via RAG_VISION_BASE_URL
    return os.getenv("RAG_VISION_BASE_URL") or os.getenv("RAG_LLM_BASE_URL") or "http://127.0.0.1:11434/v1"


_VISION_PROMPT_IMAGE = (
    "Descreva este gráfico em português de forma fiel e concisa. "
    "Transcreva título, eixos, legendas, unidades e TODOS os valores numéricos visíveis. "
    "Se houver série temporal, liste os pontos (ano/mês: valor). "
    "Descreva a tendência em 1 frase. Não invente números."
)
_VISION_PROMPT_TABLE = (
    "Transcreva esta tabela em português. "
    "Extraia cabeçalhos e cada linha como 'coluna: valor'. "
    "Preserve todos os números exatamente como aparecem. Não invente."
)


def _describe_with_ollama(pil_img, prompt: str) -> str:
    """Chama Ollama vision (OpenAI-compat) com imagem base64. Retorna '' em falha."""
    try:
        import base64
        import io
        # Reduz para 1024px max para economizar tokens/tempo (kg usa 1024 thumb)
        img = pil_img.copy()
        img.thumbnail((1024, 1024))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        from openai import OpenAI
        base_url = _vision_base_url()
        # Ollama ignora api_key mas cliente exige
        api_key = os.getenv("RAG_VISION_API_KEY") or os.getenv("OLLAMA_API_KEY") or "ollama"
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=30.0)
        resp = client.chat.completions.create(
            model=_vision_model(),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            temperature=0.0,
            max_tokens=900,
        )
        txt = (resp.choices[0].message.content or "").strip()
        return txt[:2000]
    except Exception as e:
        print(f"  Aviso: visão Ollama falhou ({_vision_model()} @ {_vision_base_url()}): {e}")
        return ""


def extract_pdf_text(pdf_path: Path, source_file: str | None = None, documents_dir: Path | None = None) -> list:
    """Extrai texto por página via PyMuPDF; fallback visão local para PDFs image-based (scanned)."""
    source_file = source_file or pdf_path.name
    chunks = []
    doc = fitz.open(str(pdf_path))
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text().strip()
        if text and len(text) >= 80:
            chunks.append({
                "chunk_id": str(uuid.uuid4()),
                "source_file": source_file,
                "page": page_num,
                "text": text,
                "type": "text",
            })
        elif _vision_enabled():
            # Fallback P1: página image-based (scanned) sem texto — tenta OCR local primeiro (rápido), depois qwen2.5vl
            # Limita a 8 páginas por PDF para não explodir tempo (605 PDFs * 30 págs * 5s = horas)
            drawings = page.get_drawings()
            if len(drawings) < 50 and len(text) < 80:
                if page_num > 8 and len(doc) > 12:
                    # evita custo excessivo em PDFs antigos muito longos — pula páginas do meio
                    if text:
                        chunks.append({"chunk_id": str(uuid.uuid4()), "source_file": source_file, "page": page_num, "text": text, "type": "text"})
                    continue
                try:
                    pix = page.get_pixmap(dpi=150)
                    from PIL import Image as _PILImage
                    img = _PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    vision_text = ""
                    # 1) tenta tesseract rápido primeiro
                    try:
                        import pytesseract
                        ocr = pytesseract.image_to_string(img, lang="por").strip()
                        if ocr and len(ocr) >= 40:
                            vision_text = ocr[:2000]
                    except Exception:
                        pass
                    # 2) se OCR falhou ou curto, tenta qwen2.5vl local
                    if (not vision_text or len(vision_text) < 80) and os.getenv("RAG_VISION_FULLPAGE", "1") == "1":
                        prompt = (
                            "Transcreva fielmente todo o texto visível desta página de boletim econômico em português. "
                            "Preserve títulos, subtítulos e valores numéricos. Não invente."
                        )
                        qwen_text = _describe_with_ollama(img, prompt)
                        if qwen_text and len(qwen_text.strip()) >= 40:
                            vision_text = qwen_text
                    if vision_text and len(vision_text.strip()) >= 40:
                        chunks.append({
                            "chunk_id": str(uuid.uuid4()),
                            "source_file": source_file,
                            "page": page_num,
                            "text": f"[Visão OCR — página {page_num}]\n{vision_text}",
                            "type": "text",
                            "vision_fallback": True,
                        })
                        print(f"    visão full-page p.{page_num}: {vision_text[:80]}...")
                    elif text:
                        chunks.append({
                            "chunk_id": str(uuid.uuid4()),
                            "source_file": source_file,
                            "page": page_num,
                            "text": text,
                            "type": "text",
                        })
                except Exception as e:
                    print(f"  Aviso: visão full-page falhou p.{page_num} de {pdf_path.name}: {e}")
                    if text:
                        chunks.append({
                            "chunk_id": str(uuid.uuid4()),
                            "source_file": source_file,
                            "page": page_num,
                            "text": text,
                            "type": "text",
                        })
            elif text:
                chunks.append({
                    "chunk_id": str(uuid.uuid4()),
                    "source_file": source_file,
                    "page": page_num,
                    "text": text,
                    "type": "text",
                })
    doc.close()
    return chunks


def _figure_regions(page) -> list:
    """Detecta regiões de figura por bbox real: imagens embutidas + cluster de drawings.

    Retorna lista de fitz.Rect. Ignora regiões <5% da página (logos/cabeçalhos).
    """
    regions: list = []
    try:
        page_area = max(float(page.rect.width * page.rect.height), 1.0)
        # 1) imagens raster embutidas
        try:
            for img in page.get_images(full=True):
                try:
                    bbox = page.get_image_bbox(img)
                except Exception:
                    continue
                if bbox is None or bbox.is_empty:
                    continue
                if bbox.width < 50 or bbox.height < 50:
                    continue
                if (bbox.width * bbox.height) / page_area < 0.05:
                    continue
                regions.append(bbox)
        except Exception:
            pass
        # 2) cluster de drawings vetoriais (gráficos)
        try:
            drawings = page.get_drawings()
        except Exception:
            drawings = []
        if len(drawings) >= 40:
            try:
                union = None
                for d in drawings:
                    r = d.get("rect")
                    if r is None:
                        continue
                    union = r if union is None else (union | r)
                if union is not None and not union.is_empty:
                    if (union.width * union.height) / page_area >= 0.05:
                        # padding pequeno para não cortar eixos/legendas
                        pad = 6
                        union = fitz.Rect(
                            max(union.x0 - pad, page.rect.x0),
                            max(union.y0 - pad, page.rect.y0),
                            min(union.x1 + pad, page.rect.x1),
                            min(union.y1 + pad, page.rect.y1),
                        )
                        regions.append(union)
            except Exception:
                pass
    except Exception:
        pass
    return regions[:4]


def extract_pdf_images(pdf_path: Path, source_file: str | None = None, documents_dir: Path | None = None) -> list:
    """Extrai figuras por bbox real (recorte) quando visão está ativa (local Ollama).

    Cada figura vira 1 nó `type=image` com descrição via qwen2.5vl (fallback tesseract).
    Regiões <5% da página são ignoradas (logos/cabeçalhos).
    """
    if not _vision_enabled():
        return []
    source_file = source_file or pdf_path.name
    images = []
    try:
        try:
            import pytesseract  # type: ignore
            _has_ocr = True
        except Exception:
            _has_ocr = False
        doc = fitz.open(str(pdf_path))
        for page_num, page in enumerate(doc, start=1):
            regions = _figure_regions(page)
            if not regions:
                continue
            for fig_idx, bbox in enumerate(regions):
                try:
                    pix = page.get_pixmap(clip=bbox, dpi=150)
                    from PIL import Image as _PILImage
                    img = _PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    vision_text = _describe_with_ollama(img, _VISION_PROMPT_IMAGE)
                    if documents_dir is not None:
                        img_dir = Path(documents_dir) / "images"
                        img_dir.mkdir(parents=True, exist_ok=True)
                        safe_name = source_file.replace("/", "_").replace("\\", "_")
                        img_path = img_dir / f"{safe_name}_p{page_num}_fig{fig_idx}.jpg"
                        thumb = img.copy()
                        thumb.thumbnail((512, 512))
                        thumb.save(img_path, "JPEG", quality=82)
                        rel_path = str(img_path.relative_to(Path(documents_dir).parent)) if documents_dir else str(img_path)
                    else:
                        rel_path = ""
                    ocr_text = ""
                    if not vision_text and _has_ocr:
                        try:
                            ocr_text = pytesseract.image_to_string(img, lang="por").strip()[:800]
                        except Exception:
                            ocr_text = ""
                    combined = (vision_text or ocr_text or "").strip()
                    if combined:
                        images.append({
                            "image_id": str(uuid.uuid4()),
                            "source_file": source_file,
                            "page": page_num,
                            "bbox": [round(float(bbox.x0), 1), round(float(bbox.y0), 1),
                                     round(float(bbox.x1), 1), round(float(bbox.y1), 1)],
                            "image_path": rel_path,
                            "ocr_text": combined,
                            "vision_text": vision_text,
                            "vision_model": _vision_model() if vision_text else "",
                            "type": "image",
                        })
                        if vision_text:
                            print(f"    visão [{_vision_model()}] p.{page_num} fig{fig_idx}: {vision_text[:90]}...")
                except Exception as e:
                    print(f"  Aviso: falha ao renderizar figura p.{page_num} de {pdf_path.name}: {e}")
        doc.close()
    except Exception as e:
        print(f"  Aviso: falha na extração de imagens de {pdf_path.name}: {e}")
    return images


def extract_pdf_tables(pdf_path: Path, source_file: str | None = None) -> list:
    """Extrai tabelas de PDF via Camelot (lattice → stream como fallback)."""
    source_file = source_file or pdf_path.name
    tables = []
    try:
        result = camelot.read_pdf(str(pdf_path), pages="all", flavor="lattice")
        if result.n == 0:
            result = camelot.read_pdf(str(pdf_path), pages="all", flavor="stream")

        for i, table in enumerate(result):
            df = table.df
            if df.empty:
                continue
            tables.append({
                "table_id": str(uuid.uuid4()),
                "source_file": source_file,
                "page": table.page,
                "table_index": i,
                "markdown": df.to_markdown(index=False),
                "rows": df.shape[0],
                "cols": df.shape[1],
                "type": "table",
            })
    except Exception as e:
        print(f"  Aviso: falha ao extrair tabelas de {pdf_path.name}: {e}")
    return tables


def extract_spreadsheet(file_path: Path, source_file: str | None = None) -> list:
    """Extrai tabelas de CSV/XLSX/XLS via pandas. Cada aba vira uma tabela."""
    source_file = source_file or file_path.name
    tables = []
    try:
        if file_path.suffix.lower() == ".csv":
            df = None
            for sep in [",", ";", "\t"]:
                try:
                    candidate = pd.read_csv(file_path, sep=sep)
                    if candidate.shape[1] > 1:
                        df = candidate
                        break
                except Exception:
                    continue
            if df is None:
                df = pd.read_csv(file_path)
            sheets = {"Planilha": df}
        else:
            xl = pd.ExcelFile(file_path)
            sheets = {name: xl.parse(name) for name in xl.sheet_names}

        for sheet_name, df in sheets.items():
            df = df.dropna(how="all").dropna(axis=1, how="all")
            if df.empty:
                continue
            tables.append({
                "table_id": str(uuid.uuid4()),
                "source_file": source_file,
                "page": sheet_name,
                "table_index": 0,
                "markdown": df.to_markdown(index=False),
                "rows": df.shape[0],
                "cols": df.shape[1],
                "type": "table",
            })
    except Exception as e:
        print(f"  Aviso: erro ao ler {file_path.name}: {e}")
    return tables


def save_intermediate(documents_dir: Path, text_chunks: list, tables: list, file_metadata: list):
    """Persiste o formato intermediário em documents/."""
    documents_dir.mkdir(exist_ok=True)

    with open(documents_dir / "text_chunks.json", "w", encoding="utf-8") as f:
        json.dump(text_chunks, f, ensure_ascii=False, indent=2)

    if tables:
        df_tables = pd.DataFrame(tables)
        df_tables["page"] = df_tables["page"].astype(str)
        df_tables.to_parquet(documents_dir / "tables.parquet", index=False)

    with open(documents_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(
            {"files": file_metadata, "generated_at": datetime.now().isoformat()},
            f,
            ensure_ascii=False,
            indent=2,
        )


def to_llama_documents(text_chunks: list, tables: list, images: list | None = None) -> list:
    """Converte chunks, tabelas e imagens para LlamaIndex Documents."""
    docs = []
    for chunk in text_chunks:
        docs.append(Document(
            text=chunk["text"],
            metadata={
                "source_file": chunk["source_file"],
                "page": chunk["page"],
                "type": "text",
                "chunk_id": chunk["chunk_id"],
            },
        ))
    for table in tables:
        docs.append(Document(
            text=f"Tabela extraída de {table['source_file']} (página/aba: {table['page']}):\n\n{table['markdown']}",
            metadata={
                "source_file": table["source_file"],
                "page": str(table["page"]),
                "type": "table",
                "table_id": table["table_id"],
                "rows": table["rows"],
                "cols": table["cols"],
            },
        ))
    for img in (images or []):
        # Texto para o vetor textual = OCR (ruidoso mas dá contexto); imagem em si vai para CLIP em indexing.py
        ocr = (img.get("ocr_text") or "").strip()
        caption = f"Gráfico extraído de {img['source_file']} (página {img['page']}, bbox {img.get('bbox')})"
        if ocr:
            caption += f"\nTexto OCR: {ocr[:600]}"
        docs.append(Document(
            text=caption,
            metadata={
                "source_file": img["source_file"],
                "page": str(img["page"]),
                "type": "image",
                "image_id": img["image_id"],
                "image_path": img.get("image_path", ""),
                "bbox": str(img.get("bbox", "")),
            },
        ))
    return docs


def load_documents(
    data_dir: str,
    source_files: list[str] | None = None,
    *,
    save_output: bool = True,
) -> list:
    """
    Pipeline de ingestão:
      1. Extrai texto (PyMuPDF) e tabelas (Camelot) de PDFs
      2. Extrai tabelas de planilhas (pandas)
      3. Salva formato intermediário em documents/
      4. Retorna LlamaIndex Documents prontos para indexação
    """
    path = Path(data_dir)
    if not path.exists():
        os.makedirs(data_dir, exist_ok=True)
        print(f"Aviso: Diretório '{data_dir}' criado. Adicione documentos e rode novamente.")
        return []

    requested = set(source_files) if source_files is not None else None
    arquivos = [
        file_path
        for file_path in sorted(path.rglob("*"))
        if file_path.is_file()
        and file_path.suffix.lower() in SUPPORTED_EXTS
        and (
            requested is None
            or file_path.relative_to(path).as_posix() in requested
        )
    ]
    if not arquivos:
        print("Aviso: Nenhum arquivo suportado encontrado em 'data/'.")
        return []

    print(f"Encontrados {len(arquivos)} arquivo(s) em {data_dir}...")

    all_text_chunks, all_tables, all_images, file_metadata = [], [], [], []

    documents_dir_for_images = path.parent / "documents" if save_output else None
    for file_path in arquivos:
        source_file = file_path.relative_to(path).as_posix()
        print(f"  Processando: {source_file}")
        text_chunks, tables, images = [], [], []

        if file_path.suffix.lower() == ".pdf":
            text_chunks = extract_pdf_text(file_path, source_file, documents_dir=documents_dir_for_images)
            tables = extract_pdf_tables(file_path, source_file)
            images = extract_pdf_images(file_path, source_file, documents_dir=documents_dir_for_images)
        elif file_path.suffix.lower() in {".csv", ".xlsx", ".xls"}:
            tables = extract_spreadsheet(file_path, source_file)
        elif file_path.suffix.lower() == ".txt":
            text = file_path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                text_chunks.append({
                    "chunk_id": str(uuid.uuid4()),
                    "source_file": source_file,
                    "page": 1,
                    "text": text,
                    "type": "text",
                })

        all_text_chunks.extend(text_chunks)
        all_tables.extend(tables)
        all_images.extend(images)
        file_metadata.append({
            "file_name": source_file,
            "file_type": file_path.suffix.lower().lstrip("."),
            "text_chunks": len(text_chunks),
            "tables": len(tables),
            "images": len(images),
            "processed_at": datetime.now().isoformat(),
        })
        print(f"    -> {len(text_chunks)} chunk(s) de texto, {len(tables)} tabela(s), {len(images)} imagem(ns)")

    if save_output:
        documents_dir = path.parent / "documents"
        save_intermediate(documents_dir, all_text_chunks, all_tables, file_metadata)

        print(f"\nFormato intermediário salvo em: {documents_dir}")
        print(f"  text_chunks.json : {len(all_text_chunks)} chunks")
        print(f"  tables.parquet   : {len(all_tables)} tabelas")
        if all_images:
            print(f"  images         : {len(all_images)} gráficos")

    docs = to_llama_documents(all_text_chunks, all_tables, all_images)
    print(f"  Total de documentos para indexação: {len(docs)}")
    return docs


if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    docs = load_documents(DATA_DIR)
    if docs:
        print("\nAmostra do primeiro documento:")
        print(docs[0].text[:300])
        print("Metadados:", docs[0].metadata)
