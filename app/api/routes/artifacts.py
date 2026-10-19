from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import FileResponse

from app.core.config import settings

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _safe_path(rel_path: str) -> str:
    base = os.path.abspath(settings.ARTIFACTS_DIR)
    requested = os.path.abspath(os.path.join(base, rel_path))
    if requested != base and not requested.startswith(base + os.sep):
        raise HTTPException(status_code=400, detail="invalid artifact path")
    if not os.path.isfile(requested):
        raise HTTPException(status_code=404, detail="artifact not found")
    return requested


@router.get("/{rel_path:path}")
async def get_artifact(rel_path: str = Path(...)):
    file_path = _safe_path(rel_path)
    return FileResponse(file_path)
