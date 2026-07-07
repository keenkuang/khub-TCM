from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Attachment:
    kind: str
    path: str
    hash: str = ""

@dataclass
class RawDoc:
    id: str
    title: str
    content: str
    format: str = "markdown"
    updated_at: str = ""
    etag: str = ""
    attachments: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

@dataclass
class CanonicalDoc:
    canonical_id: str
    title: str
    content: str
    source: str
    source_id: str
    origin: str = "source"
    format: str = "markdown"
    version: int = 1
    updated_at: str = ""
    hash: str = ""
    attachments: list = field(default_factory=list)
    note: str = ""
    doc_type: str = "raw"

@dataclass
class SyncResult:
    status: str
    doc_id: str
    version_id: Optional[int] = None
    message: str = ""
