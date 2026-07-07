from typing import Optional
from ..db import Store
from ..llm import LLMProvider, get_provider
from .records import list_records
from .consultations import list_consultations
from ..models import CanonicalDoc

def build_summary(store: Store, patient_id: str, provider: Optional[LLMProvider] = None) -> str:
    provider = provider or get_provider("noop")
    recs = list_records(store, patient_id)
    cons = list_consultations(store, patient_id)
    ctx = f"病历 {len(recs)} 条，问诊 {len(cons)} 条。"
    prompt = f"汇总患者 {patient_id} 的数字孪生状态：{ctx}"
    return provider.complete(prompt) or f"[孪生体摘要] {ctx}"

def persist_summary(store: Store, patient_id: str, provider: Optional[LLMProvider] = None) -> str:
    text = build_summary(store, patient_id, provider)
    store.store_document(CanonicalDoc(
        canonical_id=f"twin:{patient_id}", title=f"孪生体:{patient_id}",
        content=text, source="twin", source_id=patient_id, doc_type="twin", origin="hub"))
    return text
