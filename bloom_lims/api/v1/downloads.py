"""Download endpoints for action-generated files."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from bloom_lims.api.v1.dependencies import APIUser, require_read
from bloom_lims.core.downloads import DownloadTokenError, verify_download_token


router = APIRouter(prefix="/downloads", tags=["downloads"])


@router.get("/{token}")
async def download_tmp_file(token: str, user: APIUser = Depends(require_read)):
    """Serve a tmp file referenced by a signed, expiring token."""
    try:
        abs_path, _claims = verify_download_token(token)
    except DownloadTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filename = Path(abs_path).name
    return FileResponse(
        path=str(abs_path),
        filename=filename,
        media_type="application/octet-stream",
    )

