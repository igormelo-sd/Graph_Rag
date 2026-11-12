"""Filhos indexáveis e pais literais, sem embeddings ou metadados LLM dos pais."""
import hashlib
import json
from copy import deepcopy

from llama_index.core.schema import Document, TextNode, NodeWithScore
from llama_index.core.node_parser import SentenceSplitter
from runtime import bounded_int, context_token_budget, estimate_tokens

PARENT_KEYS = ["parent_id", "parent_text", "parent_child_ids"]


def prepare_parents(documents):
    child_size = bounded_int("RAG_CHUNK_SIZE", 1024, 256, 8192)
    size = max(child_size, bounded_int("RAG_PARENT_SIZE", 3200, 512, 16000))
    splitter = SentenceSplitter(chunk_size=size, chunk_overlap=0, tokenizer=list)
    parents, texts = [], {}
    for document in documents:
        for position, text in enumerate(splitter.split_text(document.text)):
            metadata = dict(document.metadata)
            identity = hashlib.sha256(
                (str(metadata.get("source_file")) + "|" + str(metadata.get("page"))
                 + "|" + str(position) + "|" + text).encode()).hexdigest()
            metadata["parent_id"] = "parent:" + identity
            parent = Document(id_=metadata["parent_id"], text=text, metadata=metadata,
                              excluded_embed_metadata_keys=PARENT_KEYS,
                              excluded_llm_metadata_keys=PARENT_KEYS)
            parents.append(parent)
            texts[metadata["parent_id"]] = text
    return parents, texts


def attach_parents(nodes, texts):
    for node in nodes:
        identity = node.metadata.get("parent_id")
        if identity in texts:
            node.metadata["parent_text"] = texts[identity]
            for attribute in ("excluded_embed_metadata_keys", "excluded_llm_metadata_keys"):
                setattr(node, attribute, list(dict.fromkeys(getattr(node, attribute) + PARENT_KEYS)))


def expand_parents(nodes):
    """Preserva a ordem de relevância e consolida filhos do mesmo pai."""
    results, parents = [], {}
    for item in nodes:
        inner = getattr(item, "node", item)
        inner_metadata = getattr(inner, "metadata", {}) or {}
        identity = inner_metadata.get("parent_id")
        text = inner_metadata.get("parent_text")
        if inner_metadata.get("type") != "text" or not identity or not text:
            results.append(item)
            continue
        if identity in parents:
            parent = parents[identity].node
            child_ids = parent.metadata["parent_child_ids"]
            if inner.node_id not in child_ids:
                child_ids.append(inner.node_id)
            paths = json.loads(parent.metadata.get("graph_paths", "[]"))
            paths.extend(json.loads(inner.metadata.get("graph_paths", "[]")))
            parent.metadata["graph_paths"] = json.dumps(paths, ensure_ascii=False)
            continue
        metadata = deepcopy(inner.metadata)
        metadata.pop("parent_text", None)
        metadata.pop("chunk_id", None)
        metadata.pop("total_chunks_page", None)
        metadata["node_id"] = identity
        metadata["parent_child_ids"] = [inner.node_id]
        metadata["context_strategy"] = "parent_child"
        # Observações do filho não descrevem automaticamente o texto maior.
        for key in list(metadata):
            if key.startswith("ontology_"):
                metadata.pop(key)
        parent = TextNode(id_=identity, text=text, metadata=metadata,
                          excluded_embed_metadata_keys=list(dict.fromkeys(inner.excluded_embed_metadata_keys + PARENT_KEYS)),
                          excluded_llm_metadata_keys=list(dict.fromkeys(inner.excluded_llm_metadata_keys + PARENT_KEYS + ["context_strategy", "graph_paths"])))
        from domain_ontology import annotate_node
        annotate_node(parent)
        from provenance import format_source_context
        if estimate_tokens(format_source_context(parent)) + 2 > context_token_budget():
            results.append(item)  # Mantém o filho quando o pai não cabe integralmente.
            continue
        wrapped = NodeWithScore(node=parent, score=getattr(item, "score", None))
        parents[identity] = wrapped
        results.append(wrapped)
    return results
