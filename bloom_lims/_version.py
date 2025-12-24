"""
Dynamic version management for BLOOM LIMS.

Fetches version from the most recent non-prerelease GitHub release.
Caches result and provides fallback for offline/error scenarios.
"""

import logging
import os
import re
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# Fallback version if GitHub is unreachable (update when making releases)
FALLBACK_VERSION = "0.10.7"

# GitHub repo info
GITHUB_OWNER = "Daylily-Informatics"
GITHUB_REPO = "bloom"


def _parse_version_from_name(name: str) -> Optional[str]:
    """
    Extract version number from release name.
    
    Handles formats like:
    - "v0.10.7"
    - "v0.9.5 -- First Demo Version"
    - "0.8.4"
    """
    if not name:
        return None
    
    # Match version pattern: optional 'v', then numbers with dots
    match = re.match(r"v?(\d+\.\d+\.?\d*)", name.strip())
    if match:
        return match.group(1)
    return None


def _fetch_version_from_github() -> Optional[str]:
    """
    Fetch version from GitHub releases API.
    
    Returns the version string of the most recent non-prerelease,
    non-draft release, or None if unavailable.
    """
    try:
        import requests
        
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
        response = requests.get(
            url,
            timeout=5,
            params={"per_page": 20},
            headers={"Accept": "application/vnd.github.v3+json"}
        )
        response.raise_for_status()
        
        releases = response.json()
        
        # Find first non-prerelease, non-draft release
        for release in releases:
            if release.get("prerelease", False) or release.get("draft", False):
                continue
            
            # Try tag_name first, then name
            version = _parse_version_from_name(
                release.get("tag_name") or release.get("name", "")
            )
            if version:
                logger.debug(f"Fetched version {version} from GitHub releases")
                return version
        
        logger.debug("No valid non-prerelease found in GitHub releases")
        return None
        
    except ImportError:
        logger.debug("requests module not available for GitHub version fetch")
        return None
    except Exception as e:
        logger.debug(f"Failed to fetch version from GitHub: {e}")
        return None


@lru_cache(maxsize=1)
def get_version() -> str:
    """
    Get the BLOOM LIMS version.
    
    Priority:
    1. BLOOM_VERSION environment variable (for override/testing)
    2. Most recent non-prerelease GitHub release
    3. FALLBACK_VERSION constant
    
    Result is cached for the lifetime of the process.
    """
    # Allow override via environment variable
    env_version = os.environ.get("BLOOM_VERSION")
    if env_version:
        logger.debug(f"Using version from BLOOM_VERSION env var: {env_version}")
        return env_version
    
    # Try fetching from GitHub
    github_version = _fetch_version_from_github()
    if github_version:
        return github_version
    
    # Fall back to hardcoded version
    logger.debug(f"Using fallback version: {FALLBACK_VERSION}")
    return FALLBACK_VERSION


def clear_version_cache() -> None:
    """Clear the cached version (useful for testing)."""
    get_version.cache_clear()


# Module-level version for easy import
__version__ = get_version()

