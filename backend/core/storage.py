"""Media + generated documents. Cloud Storage when deployed, a directory when not.

Everything stored here is addressed by a logical path like
`voice/ord_1043.m4a` or `quotations/Q-1043.pdf`. `uri()` gives the canonical
`gs://` address we persist in Firestore; `http_path()` gives the PWA a URL it can
actually fetch, which the API serves back through `/api/media/...` in both modes
so the frontend never needs signing credentials.
"""
from __future__ import annotations

import mimetypes
import os
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


# A phone photograph of a bill is three or four megabytes and four thousand
# pixels wide. Handwriting and print are both legible far below that, and every
# one of those megabytes is paid for twice — once uploading to the model and
# once being processed by it. A longest edge of 1600px keeps a khata page
# readable while cutting the payload by roughly an order of magnitude, which is
# most of the wait the owner feels after pressing the shutter.
MODEL_MAX_EDGE = int(os.environ.get("MODEL_IMAGE_MAX_EDGE", "1600"))
MODEL_JPEG_QUALITY = int(os.environ.get("MODEL_IMAGE_QUALITY", "82"))


def for_model(blob: bytes, content_type: str) -> tuple[bytes, str]:
    """Shrink an image to something a model can read quickly.

    Returns the original untouched if it is already small, is not an image, or
    if anything at all goes wrong — a slow scan beats a failed one. The full-size
    photograph stays in storage either way, so the owner can always check a
    figure against the original.
    """
    if not content_type.startswith("image/") or len(blob) < 400_000:
        return blob, content_type
    try:
        from io import BytesIO

        from PIL import Image, ImageOps

        image = Image.open(BytesIO(blob))
        image = ImageOps.exif_transpose(image)     # honour the phone's rotation
        if max(image.size) <= MODEL_MAX_EDGE:
            return blob, content_type
        image.thumbnail((MODEL_MAX_EDGE, MODEL_MAX_EDGE), Image.LANCZOS)
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="JPEG",
                                  quality=MODEL_JPEG_QUALITY, optimize=True)
        smaller = buffer.getvalue()
        return (smaller, "image/jpeg") if len(smaller) < len(blob) \
            else (blob, content_type)
    except Exception:                                     # noqa: BLE001
        return blob, content_type


def stage_fixture(source: Path, path: str) -> str:
    """Copy a repo fixture into media storage so demo events carry a real URI."""
    if LOCAL_STORE:
        target = LOCAL_MEDIA / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return uri(path)
    return put_bytes(path, source.read_bytes(), content_type_of(source.name))
