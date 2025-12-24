"""
BLOOM LIMS Domain Utilities

Shared utility functions used across domain modules.
Extracted from bloom_lims/bobjs.py for better code organization.
"""

import os
import random
import string
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

import pytz


logger = logging.getLogger(__name__)


def get_clean_timestamp() -> str:
    """Get a clean timestamp string for logging filenames."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def generate_random_string(length: int = 10) -> str:
    """
    Generate a random alphanumeric string.
    
    Args:
        length: Length of the string to generate
        
    Returns:
        Random string of specified length
    """
    characters = string.ascii_letters + string.digits
    random_string = "".join(random.choice(characters) for _ in range(length))
    return random_string


def get_datetime_string() -> str:
    """
    Get current datetime as formatted string with timezone.
    
    Uses US/Eastern timezone by default.
    
    Returns:
        Formatted datetime string like "2024-01-15 10:30:00 EST-0500"
    """
    # Choose your desired timezone, e.g., 'US/Eastern', 'Europe/London', etc.
    timezone = pytz.timezone("US/Eastern")

    # Get current datetime with timezone
    current_datetime_with_tz = datetime.now(timezone)

    # Format as string
    datetime_string = current_datetime_with_tz.strftime("%Y-%m-%d %H:%M:%S %Z%z")

    return str(datetime_string)


def update_recursive(orig_dict: dict, update_with: dict) -> None:
    """
    Recursively update a dictionary with values from another dictionary.
    
    Modifies orig_dict in place.
    
    Args:
        orig_dict: Original dictionary to update
        update_with: Dictionary with values to merge
    """
    for key, value in update_with.items():
        if (
            key in orig_dict
            and isinstance(orig_dict[key], dict)
            and isinstance(value, dict)
        ):
            update_recursive(orig_dict[key], value)
        else:
            orig_dict[key] = value


def unique_non_empty_strings(arr: list) -> list:
    """
    Return a new array with unique strings and empty strings removed.

    Args:
        arr: List of strings
        
    Returns:
        List of unique non-empty strings
    """
    # Using a set to maintain uniqueness
    unique_strings = set()
    for s in arr:
        if s and s not in unique_strings:
            unique_strings.add(s)
    return list(unique_strings)


def setup_domain_logging():
    """
    Set up logging for domain modules.
    
    Creates rotating file handler for domain-specific logging.
    """
    os.makedirs("logs", exist_ok=True)
    
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Define the log file name with a timestamp
    log_filename = f"logs/bdb_objs_{get_clean_timestamp()}.log"

    # Stream handler (to console)
    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.INFO)

    # File handler (to file, with rotation)
    f_handler = RotatingFileHandler(log_filename, maxBytes=10485760, backupCount=10)
    f_handler.setLevel(logging.INFO)

    # Common log format
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d"
    )
    c_handler.setFormatter(formatter)
    f_handler.setFormatter(formatter)

    # Add handlers to the logger
    root_logger.addHandler(c_handler)
    root_logger.addHandler(f_handler)


# For backward compatibility with bobjs.py imports
_update_recursive = update_recursive


__all__ = [
    "get_clean_timestamp",
    "generate_random_string", 
    "get_datetime_string",
    "update_recursive",
    "_update_recursive",
    "unique_non_empty_strings",
    "setup_domain_logging",
]

