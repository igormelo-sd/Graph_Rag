"""Trecho do corpus tal como é gravado no índice JSON."""
from dataclasses import dataclass, field


@dataclass
class Chunk:
    text: str
    source: str
    page: int | None
    number: int
    metadata: dict = field(default_factory=dict)
