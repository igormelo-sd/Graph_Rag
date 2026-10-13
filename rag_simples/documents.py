"""Leitura e divisão de documentos para o RAG simples."""
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED = {".txt", ".md", ".pdf"}


@dataclass
class Chunk:
    text: str
    source: str
    page: int | None
    number: int
    metadata: dict = field(default_factory=dict)


def split_text(text: str, size: int = 1024, overlap: int = 200) -> list[str]:
    """Divide por caracteres com o mesmo parser de frases do GraphRAG."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Use tamanho > 0 e 0 <= sobreposição < tamanho.")
    from llama_index.core.node_parser import SentenceSplitter
    return SentenceSplitter(chunk_size=size, chunk_overlap=overlap, tokenizer=list).split_text(text)


def read_documents(directory: Path, size: int, overlap: int) -> list[Chunk]:
    if not directory.is_dir():
        raise ValueError(f"Pasta de documentos não encontrada: {directory}")
    chunks = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        source = path.relative_to(directory).as_posix()
        try:
            if path.suffix.lower() == ".pdf":
                from pypdf import PdfReader

                pages = [(i, page.extract_text() or "")
                         for i, page in enumerate(PdfReader(path).pages, start=1)]
            else:
                pages = [(None, path.read_text(encoding="utf-8-sig"))]
            number = 0
            for page, text in pages:
                for piece in split_text(text, size, overlap):
                    number += 1
                    chunks.append(Chunk(piece, source, page, number))
        except ImportError:
            raise
        except Exception as exc:
            raise ValueError(f"Não foi possível ler {source}: {exc}") from exc
    if not chunks:
        raise ValueError("Nenhum texto encontrado. Adicione TXT, MD ou PDF com texto selecionável.")
    return chunks


