"""
Carrier Tracking API endpoints.

Provides tracking integration for FedEx, UPS, USPS and other carriers.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from .dependencies import require_api_auth, APIUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracking", tags=["Tracking"])

# Carrier options
CARRIER_OPTIONS = ["FedEx", "UPS", "USPS", "Other"]


class TrackingRequest(BaseModel):
    """Request to track a package."""
    tracking_number: str
    carrier: str = "FedEx"


class TrackingResponse(BaseModel):
    """Tracking response data."""
    tracking_number: str
    carrier: str
    status: Optional[str] = None
    transit_time_hours: Optional[float] = None
    origin_state: Optional[str] = None
    ship_date: Optional[str] = None
    delivery_date: Optional[str] = None
    raw_data: Optional[dict] = None
    error: Optional[str] = None


def _load_fedex_credentials():
    """Load FedEx credentials from config file or environment."""
    # Try config file first
    config_path = Path.home() / ".config" / "daylily-carrier-tracking" / "fedex_prod.yaml"
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Failed to load FedEx config from {config_path}: {e}")
    
    # Fall back to environment variables
    api_key = os.environ.get("FEDEX_API_KEY")
    secret = os.environ.get("FEDEX_SECRET")
    if api_key and secret:
        return {"api_key": api_key, "secret": secret}
    
    return None


def _get_fedex_tracker():
    """Initialize FedEx tracker if available."""
    try:
        import daylily_carrier_tracking as FTD
        return FTD.FedexTracker()
    except Exception as e:
        logger.warning(f"FedEx tracker not available: {e}")
        return None


@router.get("/carriers")
async def list_carriers():
    """List available carriers."""
    return {"carriers": CARRIER_OPTIONS}


@router.get("/track/{tracking_number}")
async def track_package_get(
    tracking_number: str,
    carrier: str = "FedEx",
    user: APIUser = Depends(require_api_auth),
):
    """Track a package by tracking number (GET)."""
    return await _track_package(tracking_number, carrier)


@router.post("/track")
async def track_package_post(
    request: TrackingRequest,
    user: APIUser = Depends(require_api_auth),
):
    """Track a package by tracking number (POST)."""
    return await _track_package(request.tracking_number, request.carrier)


async def _track_package(tracking_number: str, carrier: str) -> TrackingResponse:
    """Internal function to track a package."""
    tracking_number = tracking_number.strip()
    
    if not tracking_number:
        raise HTTPException(status_code=400, detail="Tracking number is required")
    
    if carrier not in CARRIER_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid carrier. Must be one of: {CARRIER_OPTIONS}")
    
    if carrier == "FedEx":
        tracker = _get_fedex_tracker()
        if not tracker:
            return TrackingResponse(
                tracking_number=tracking_number,
                carrier=carrier,
                error="FedEx tracking not configured. Install daylily-carrier-tracking and set credentials."
            )
        
        try:
            result = tracker.get_fedex_ops_meta_ds(tracking_number)
            if result and len(result) > 0:
                data = result[0]
                transit_sec = data.get("Transit_Time_sec")
                return TrackingResponse(
                    tracking_number=tracking_number,
                    carrier=carrier,
                    status=data.get("status", "Unknown"),
                    transit_time_hours=round(transit_sec / 3600, 1) if transit_sec else None,
                    origin_state=data.get("origin_state"),
                    ship_date=data.get("ship_date"),
                    delivery_date=data.get("delivery_date"),
                    raw_data=data,
                )
            else:
                return TrackingResponse(
                    tracking_number=tracking_number,
                    carrier=carrier,
                    error="No tracking data found"
                )
        except Exception as e:
            logger.error(f"FedEx tracking error for {tracking_number}: {e}")
            return TrackingResponse(
                tracking_number=tracking_number,
                carrier=carrier,
                error=str(e)
            )
    
    # Other carriers not yet implemented
    return TrackingResponse(
        tracking_number=tracking_number,
        carrier=carrier,
        error=f"{carrier} tracking not yet implemented"
    )

