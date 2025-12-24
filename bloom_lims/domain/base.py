"""
BLOOM LIMS Domain Base

This module provides the base class imports for domain modules.
Domain classes inherit from BloomObj which is defined in bobjs.py.

The circular import is handled by importing BloomObj lazily in bobjs.py
after all classes are defined, allowing domain modules to be used.
"""

import logging

logger = logging.getLogger(__name__)


def get_bloom_obj_class():
    """
    Get the BloomObj class lazily to avoid circular imports.
    
    Returns:
        The BloomObj class from bobjs.py
    """
    # Import here to avoid circular import
    from bloom_lims.bobjs import BloomObj
    return BloomObj


# Re-export common utilities from bobjs
def get_datetime_string():
    """Get current datetime as formatted string."""
    from bloom_lims.bobjs import get_datetime_string as _get_datetime_string
    return _get_datetime_string()


def generate_random_string(length: int = 10) -> str:
    """Generate a random alphanumeric string."""
    from bloom_lims.bobjs import generate_random_string as _generate_random_string
    return _generate_random_string(length)

