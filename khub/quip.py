"""Quip adapter — pull documents from Quip via REST API v2 and ingest into store."""

import json
import urllib.request
import warnings

from khub.db import Store, compute_hash
from khub.models import CanonicalDoc

API_BASE = "https://platform.quip.com/1"


def _quip_get(path: str, access_token: str) -> dict:
    """Perform an authenticated GET against the Quip API and return decoded JSON."""
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _traverse_folder(
    folder_id: str,
    access_token: str,
    store: Store,
    depth: int = 0,
    _ingested: int = 0,
    _skipped: int = 0,
) -> tuple:
    """Recursively enumerate threads (documents) inside a folder.

    Returns (ingested_count, skipped_count).
    """
    if depth > 10:
        warnings.warn(f"Max recursion depth reached at folder {folder_id}, stopping")
        return (_ingested, _skipped)

    try:
        data = _quip_get(f"/folders/{folder_id}", access_token)
    except Exception as exc:
        warnings.warn(f"Failed to fetch folder {folder_id}: {exc}")
        return (_ingested, _skipped)

    children = data.get("children", [])

    for child in children:
        thread_id = child.get("thread_id")
        child_folder_id = child.get("folder_id")

        if thread_id:
            canonical_id = f"quip:{thread_id}"

            # Idempotency check: skip if already ingested
            existing = store.get_document(canonical_id)
            if existing is not None:
                _skipped += 1
                continue

            try:
                tdata = _quip_get(f"/threads/{thread_id}", access_token)
            except Exception as exc:
                warnings.warn(f"Failed to fetch thread {thread_id}: {exc}")
                continue

            thread = tdata.get("thread", {})
            html = tdata.get("html", "")
            title = thread.get("title", "")
            content = html

            doc = CanonicalDoc(
                canonical_id=canonical_id,
                title=title,
                content=content,
                source="quip",
                source_id=f"quip/{thread_id}",
                origin="quip",
                format="html",
                hash=compute_hash(content),
                doc_type="raw",
            )
            try:
                store.store_document(doc)
                _ingested += 1
            except Exception as exc:
                warnings.warn(f"Failed to store document {canonical_id}: {exc}")

        elif child_folder_id:
            # Recurse into sub-folder
            _ingested, _skipped = _traverse_folder(
                child_folder_id, access_token, store, depth + 1, _ingested, _skipped
            )

    return (_ingested, _skipped)


def pull_all(
    store: Store,
    access_token: str,
    root_folder: str = None,
) -> tuple:
    """Pull all Quip documents from *root_folder* (default: personal root).

    Returns (ingested_count, skipped_count).
    """
    if root_folder is None:
        root_folder = ""

    ingested, skipped = _traverse_folder(root_folder, access_token, store, depth=0)
    return (ingested, skipped)
