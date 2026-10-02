"""Resultados por consulta; nenhum dado de resposta fica no retriever compartilhado."""
from dataclasses import dataclass, field


@dataclass
class SeriesResult:
    data: str | None
    nodes: list
    chart: dict | None = None
    calculations: list[dict] = field(default_factory=list)

    def __iter__(self):
        # Compatibilidade com consumidores que desempacotam texto e fontes.
        yield self.data
        yield self.nodes


@dataclass
class AnswerResult:
    answer: str
    nodes: list
    chart: dict | None = None
    calculations: list[dict] = field(default_factory=list)

    def __iter__(self):
        yield self.answer
        yield self.nodes
