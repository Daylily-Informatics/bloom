"""
BLOOM LIMS API v1 - Actions Endpoints

Endpoints for action management (aliquot, transfer, split, pool, etc.).
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .dependencies import require_api_auth, APIUser


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/actions", tags=["Actions"])


def get_bdb(username: str = "api-user"):
    """Get database connection."""
    from bloom_lims.db import BLOOMdb3
    return BLOOMdb3(app_username=username)


class AliquotRequest(BaseModel):
    """Request for aliquot action."""
    source_euid: str = Field(..., description="Source content EUID")
    num_aliquots: int = Field(1, ge=1, le=100, description="Number of aliquots")
    volume_per_aliquot: Optional[float] = Field(None, description="Volume per aliquot")
    volume_unit: str = Field("uL", description="Volume unit")


class TransferRequest(BaseModel):
    """Request for transfer action."""
    source_euid: str = Field(..., description="Source content EUID")
    destination_euid: str = Field(..., description="Destination container/well EUID")
    volume: Optional[float] = Field(None, description="Volume to transfer")
    volume_unit: str = Field("uL", description="Volume unit")


class PoolRequest(BaseModel):
    """Request for pool action."""
    source_euids: List[str] = Field(..., description="List of source content EUIDs")
    pool_name: Optional[str] = Field(None, description="Name for the pooled content")


class SplitRequest(BaseModel):
    """Request for split action."""
    source_euid: str = Field(..., description="Source content EUID")
    num_splits: int = Field(2, ge=2, le=100, description="Number of splits")


@router.post("/aliquot", response_model=Dict[str, Any])
async def create_aliquot(
    request: AliquotRequest,
    user: APIUser = Depends(require_api_auth),
):
    """Create aliquots from a source content."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent
        
        bc = BloomContent(bdb)
        source = bc.get_by_euid(request.source_euid)
        
        if not source:
            raise HTTPException(status_code=404, detail=f"Source not found: {request.source_euid}")
        
        # Create aliquots
        aliquots = bc.aliquot(
            source,
            num_aliquots=request.num_aliquots,
            volume=request.volume_per_aliquot,
            volume_unit=request.volume_unit,
        )
        
        return {
            "success": True,
            "source_euid": request.source_euid,
            "aliquots": [
                {"euid": a.euid, "name": a.name}
                for a in aliquots
            ],
            "count": len(aliquots),
            "message": f"Created {len(aliquots)} aliquots",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating aliquots: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/transfer", response_model=Dict[str, Any])
async def transfer_content(
    request: TransferRequest,
    user: APIUser = Depends(require_api_auth),
):
    """Transfer content to a destination."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent, BloomContainer
        
        bc = BloomContent(bdb)
        bcon = BloomContainer(bdb)
        
        source = bc.get_by_euid(request.source_euid)
        if not source:
            raise HTTPException(status_code=404, detail=f"Source not found: {request.source_euid}")
        
        destination = bcon.get_by_euid(request.destination_euid)
        if not destination:
            destination = bc.get_by_euid(request.destination_euid)
        if not destination:
            raise HTTPException(status_code=404, detail=f"Destination not found: {request.destination_euid}")
        
        # Perform transfer
        bc.transfer(
            source,
            destination,
            volume=request.volume,
            volume_unit=request.volume_unit,
        )
        
        return {
            "success": True,
            "source_euid": request.source_euid,
            "destination_euid": request.destination_euid,
            "message": "Transfer completed successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error transferring content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pool", response_model=Dict[str, Any])
async def pool_content(
    request: PoolRequest,
    user: APIUser = Depends(require_api_auth),
):
    """Pool multiple content items into one."""
    try:
        bdb = get_bdb(user.email)
        from bloom_lims.bobjs import BloomContent
        
        bc = BloomContent(bdb)
        
        sources = []
        for euid in request.source_euids:
            source = bc.get_by_euid(euid)
            if not source:
                raise HTTPException(status_code=404, detail=f"Source not found: {euid}")
            sources.append(source)
        
        # Create pool
        pool = bc.pool(sources, name=request.pool_name)
        
        return {
            "success": True,
            "source_euids": request.source_euids,
            "pool_euid": pool.euid,
            "pool_name": pool.name,
            "message": f"Pooled {len(sources)} items",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pooling content: {e}")
        raise HTTPException(status_code=500, detail=str(e))

