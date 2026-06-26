import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone


KBS_DIR = os.path.expanduser("~/.advai/kbs")
KB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_root() -> None:
    os.makedirs(KBS_DIR, exist_ok=True)


def _validate_kb_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("Knowledge base name cannot be empty")
    if not KB_NAME_PATTERN.match(cleaned):
        raise ValueError(
            "Knowledge base name may only contain letters, numbers, dots, underscores, and hyphens"
        )
    return cleaned


def _kb_dir(name: str) -> str:
    return os.path.join(KBS_DIR, _validate_kb_name(name))


def _docs_dir(name: str) -> str:
    return os.path.join(_kb_dir(name), "docs")


def _metadata_path(name: str) -> str:
    return os.path.join(_kb_dir(name), "metadata.json")


def _load_metadata(name: str) -> dict:
    metadata_path = _metadata_path(name)
    if not os.path.exists(metadata_path):
        raise FileNotFoundError(f"Knowledge base '{name}' is not initialized")
    with open(metadata_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_metadata(name: str, metadata: dict) -> None:
    with open(_metadata_path(name), "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)


def _stored_name_for_path(source_path: str) -> str:
    basename = os.path.basename(source_path)
    digest = hashlib.sha1(source_path.encode("utf-8")).hexdigest()[:12]
    return f"{digest}-{basename}"


def create_knowledge_base(name: str) -> dict:
    kb_name = _validate_kb_name(name)
    kb_dir = _kb_dir(kb_name)
    if os.path.exists(kb_dir):
        raise FileExistsError(f"Knowledge base '{kb_name}' already exists")

    _ensure_root()
    os.makedirs(_docs_dir(kb_name), exist_ok=False)
    metadata = {
        "name": kb_name,
        "created_at": _utc_now(),
        "documents": [],
    }
    _save_metadata(kb_name, metadata)
    return metadata


def add_document(kb_name: str, source_path: str) -> dict:
    metadata = _load_metadata(kb_name)
    resolved_source = os.path.abspath(os.path.expanduser(source_path))
    if not os.path.isfile(resolved_source):
        raise FileNotFoundError(f"Document '{source_path}' was not found")

    os.makedirs(_docs_dir(kb_name), exist_ok=True)
    stored_name = _stored_name_for_path(resolved_source)
    target_path = os.path.join(_docs_dir(kb_name), stored_name)
    shutil.copy2(resolved_source, target_path)

    now = _utc_now()
    doc_record = {
        "id": hashlib.sha1(resolved_source.encode("utf-8")).hexdigest()[:12],
        "display_name": os.path.basename(resolved_source),
        "source_path": resolved_source,
        "stored_name": stored_name,
        "added_at": now,
        "synced_at": now,
    }

    documents = metadata.setdefault("documents", [])
    existing_index = next(
        (index for index, item in enumerate(documents) if item.get("source_path") == resolved_source),
        None,
    )
    if existing_index is None:
        documents.append(doc_record)
    else:
        doc_record["added_at"] = documents[existing_index].get("added_at", now)
        documents[existing_index] = doc_record

    _save_metadata(kb_name, metadata)
    return doc_record


def search_knowledge_base(kb_name: str, query: str, limit: int = 20) -> list[dict]:
    metadata = _load_metadata(kb_name)
    needle = (query or "").strip()
    if not needle:
        raise ValueError("Search query cannot be empty")

    results = []
    needle_lower = needle.lower()
    for doc in metadata.get("documents", []):
        stored_name = doc.get("stored_name")
        if not stored_name:
            continue
        stored_path = os.path.join(_docs_dir(kb_name), stored_name)
        if not os.path.isfile(stored_path):
            continue
        with open(stored_path, "r", encoding="utf-8", errors="ignore") as handle:
            for line_number, line in enumerate(handle, start=1):
                if needle_lower in line.lower():
                    results.append(
                        {
                            "document": doc.get("display_name") or stored_name,
                            "source_path": doc.get("source_path"),
                            "line_number": line_number,
                            "line": line.rstrip("\n"),
                        }
                    )
                    if len(results) >= limit:
                        return results
    return results


def sync_knowledge_base(kb_name: str) -> dict:
    metadata = _load_metadata(kb_name)
    synced = 0
    missing = []

    for doc in metadata.get("documents", []):
        source_path = doc.get("source_path")
        stored_name = doc.get("stored_name")
        if not source_path or not stored_name:
            continue
        if not os.path.isfile(source_path):
            missing.append(source_path)
            continue

        target_path = os.path.join(_docs_dir(kb_name), stored_name)
        shutil.copy2(source_path, target_path)
        doc["synced_at"] = _utc_now()
        synced += 1

    _save_metadata(kb_name, metadata)
    return {
        "name": kb_name,
        "document_count": len(metadata.get("documents", [])),
        "synced": synced,
        "missing": missing,
    }
