"""
BLOOM LIMS Cached Repository

Provides caching integration for database operations.

This module wraps common database queries with caching to improve performance
for frequently accessed data like templates, instances, and lineage records.

Usage:
    from bloom_lims.core.cached_repository import CachedRepository
    
    repo = CachedRepository(bdb)
    template = repo.get_template_by_euid("WFT_ABC123_X")  # Cached
    repo.invalidate_template("WFT_ABC123_X")  # Invalidate on update
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from bloom_lims.config import get_settings
from bloom_lims.core.cache import (
    cached,
    cache_invalidate,
    get_cache_stats,
    get_global_cache,
    LRUCache,
    create_cache,
)

logger = logging.getLogger(__name__)


class CachedRepository:
    """
    Repository with integrated caching for BLOOM database operations.
    
    Wraps database queries with caching layer for improved performance.
    """
    
    def __init__(self, bdb, cache: Optional[LRUCache] = None):
        """
        Initialize cached repository.
        
        Args:
            bdb: BLOOMdb3 database instance
            cache: Optional custom cache (defaults to global cache)
        """
        self._bdb = bdb
        self._session = bdb.session
        self._Base = bdb.Base
        self._settings = get_settings()
        
        # Use custom cache or global cache based on settings
        if cache is not None:
            self._cache = cache
        elif self._settings.features.enable_api_caching:
            self._cache = get_global_cache()
        else:
            # Create a disabled cache (TTL=0 means immediate expiration)
            self._cache = create_cache(max_size=1, default_ttl=0)
    
    @property
    def cache(self) -> LRUCache:
        """Get the cache instance."""
        return self._cache
    
    def get_template_by_euid(self, euid: str) -> Optional[Any]:
        """
        Get a template by EUID with caching.
        
        Templates are cached longer (1 hour by default) since they rarely change.
        """
        cache_key = f"{self._settings.cache.template_prefix}{euid}"
        
        # Check cache first
        cached_value = self._cache.get(cache_key)
        if cached_value is not None:
            logger.debug(f"Cache hit for template {euid}")
            return cached_value
        
        # Query database
        result = (
            self._session.query(self._Base.classes.generic_template)
            .filter(
                self._Base.classes.generic_template.euid == euid,
                self._Base.classes.generic_template.is_deleted == False,
            )
            .first()
        )
        
        # Cache the result
        if result is not None:
            self._cache.set(cache_key, result, self._settings.cache.template_ttl)
            logger.debug(f"Cached template {euid}")
        
        return result
    
    def get_instance_by_euid(self, euid: str) -> Optional[Any]:
        """Get an instance by EUID with caching."""
        cache_key = f"{self._settings.cache.instance_prefix}{euid}"
        
        cached_value = self._cache.get(cache_key)
        if cached_value is not None:
            logger.debug(f"Cache hit for instance {euid}")
            return cached_value
        
        result = (
            self._session.query(self._Base.classes.generic_instance)
            .filter(
                self._Base.classes.generic_instance.euid == euid,
                self._Base.classes.generic_instance.is_deleted == False,
            )
            .first()
        )
        
        if result is not None:
            self._cache.set(cache_key, result, self._settings.cache.instance_ttl)
            logger.debug(f"Cached instance {euid}")
        
        return result
    
    def query_templates_by_type(
        self,
        super_type: Optional[str] = None,
        btype: Optional[str] = None,
        b_sub_type: Optional[str] = None,
        version: Optional[str] = None,
    ) -> List[Any]:
        """Query templates by type components with caching."""
        # Build cache key from query parameters
        cache_key = f"{self._settings.cache.query_prefix}tmpl:{super_type}:{btype}:{b_sub_type}:{version}"
        
        cached_value = self._cache.get(cache_key)
        if cached_value is not None:
            logger.debug(f"Cache hit for template query")
            return cached_value
        
        query = self._session.query(self._Base.classes.generic_template)
        
        if super_type is not None:
            query = query.filter(
                self._Base.classes.generic_template.super_type == super_type
            )
        if btype is not None:
            query = query.filter(self._Base.classes.generic_template.btype == btype)
        if b_sub_type is not None:
            query = query.filter(
                self._Base.classes.generic_template.b_sub_type == b_sub_type
            )
        if version is not None:
            query = query.filter(self._Base.classes.generic_template.version == version)
        
        query = query.filter(
            self._Base.classes.generic_template.is_deleted == False
        )
        
        result = query.all()
        self._cache.set(cache_key, result, self._settings.cache.query_ttl)

        return result

    def invalidate_template(self, euid: str) -> bool:
        """
        Invalidate cached template entry.

        Call this after updating a template.
        """
        cache_key = f"{self._settings.cache.template_prefix}{euid}"
        invalidated = self._cache.invalidate(cache_key)
        if invalidated:
            logger.debug(f"Invalidated template cache for {euid}")
        return invalidated

    def invalidate_instance(self, euid: str) -> bool:
        """
        Invalidate cached instance entry.

        Call this after updating an instance.
        """
        cache_key = f"{self._settings.cache.instance_prefix}{euid}"
        invalidated = self._cache.invalidate(cache_key)
        if invalidated:
            logger.debug(f"Invalidated instance cache for {euid}")
        return invalidated

    def invalidate_query_cache(self) -> int:
        """
        Invalidate all query cache entries.

        Call this after bulk updates or schema changes.
        """
        return self._cache.invalidate_prefix(self._settings.cache.query_prefix)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return get_cache_stats(self._cache)

    def clear_all(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        logger.info("Cleared all cache entries")

