"""Media + generated documents. Cloud Storage when deployed, a directory when not.

Everything stored here is addressed by a logical path like
`voice/ord_1043.m4a` or `quotations/Q-1043.pdf`. `uri()` gives the canonical
`gs://` address we persist in Firestore; `http_path()` gives the PWA a URL it can
actually fetch, which the API serves back through `/api/media/...` in both modes
so the frontend never needs signing credentials.
"""
from __future__ import annotations

import mimetypes
import shutil
from functools import lru_cache
from pathlib import Path

from core.config import GCS_BUCKET, LOCAL_DATA_DIR, LOCAL_STORE

LOCAL_MEDIA = Path(LOCAL_DATA_DIR) / "media"


@lru_cache(maxsize=1)
def _bucket():
    from google.cloud import storage
    return storage.Client().bucket(GCS_BUCKET)


def uri(path: str) -> str:
    return f"gs://{GCS_BUCKET}/{path.lstrip('/')}"


def http_path(gs_or_path: str | None) -> str | None:
    """`gs://galla-media/voice/x.m4a` -> `/api/media/voice/x.m4a`"""
    if not gs_or_path:
        return None
    path = gs_or_path
    if path.startswith("gs://"):
        path = path[len("gs://"):].split("/", 1)[-1]
    return "/api/media/" + path.lstrip("/")


def put_bytes(path: str, data: bytes, content_type: str | None = None) -> str:
    path = path.lstrip("/")
    content_type = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
    if LOCAL_STORE:
        target = LOCAL_MEDIA / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    else:
        _bucket().blob(path).upload_from_string(data, content_type=content_type)
    return uri(path)


def get_bytes(path_or_uri: str) -> bytes | None:
    path = path_or_uri
    if path.startswith("gs://"):
        path = path[len("gs://"):].split("/", 1)[-1]
    path = path.lstrip("/")
    if LOCAL_STORE:
        target = LOCAL_MEDIA / path
        return target.read_bytes() if target.exists() else None
    blob = _bucket().blob(path)
    return blob.download_as_bytes() if blob.exists() else None


def content_type_of(path_or_uri: str) -> str:
    return mimetypes.guess_type(path_or_uri)[0] or "application/octet-stream"


def stage_fixture(source: Path, path: str) -> str:
    """Copy a repo fixture into media storage so demo events carry a real URI."""
    if LOCAL_STORE:
        target = LOCAL_MEDIA / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return uri(path)
    return put_bytes(path, source.read_bytes(), content_type_of(source.name))
