from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Question:
    id: Optional[int] = None
    kind: str = "mcq"          # 'mcq' | 'case'
    stem: str = ""
    options: List[str] = field(default_factory=list)
    answer: str = ""
    explanation: str = ""
    source_doc: str = ""
