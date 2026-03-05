from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse


router = APIRouter()


@router.get("/list-scripts", response_class=JSONResponse)
async def list_scripts(directory: str = Query(..., description="Directory to search for .js files")):
    try:
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Invalid directory: {directory}")

        js_files = [str(file) for file in dir_path.rglob("*.js")]
        logging.info("Found %s .js files in %s", len(js_files), directory)
        return JSONResponse(content={"scripts": js_files}, status_code=200)
    except HTTPException:
        raise
    except Exception as exc:
        logging.error("Error listing scripts: %s", exc)
        raise HTTPException(status_code=500, detail=f"An error occurred: {exc}")


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    file_path = Path("static") / "favicon.ico"
    return FileResponse(str(file_path))

