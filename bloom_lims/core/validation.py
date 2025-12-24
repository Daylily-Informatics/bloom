"""
BLOOM LIMS Validation Framework

Provides validation decorators and utilities for input validation.

Usage:
    from bloom_lims.core.validation import validate_euid, validated
    
    # Direct validation
    if validate_euid(euid):
        process(euid)
    
    # Decorator-based validation
    @validated(euid=validate_euid, uuid=validate_uuid)
    def process_object(euid: str, uuid: str):
        ...
"""

import re
import uuid as uuid_module
import logging
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union, TypeVar, ParamSpec

logger = logging.getLogger(__name__)

# Type variables for generic decorators
P = ParamSpec('P')
T = TypeVar('T')


class ValidationError(ValueError):
    """
    Exception raised when validation fails.
    
    Attributes:
        field: Name of the field that failed validation
        value: The invalid value
        message: Description of the validation failure
    """
    
    def __init__(self, field: str, value: Any, message: str):
        self.field = field
        self.value = value
        self.message = message
        super().__init__(f"Validation failed for '{field}': {message}")


# EUID pattern: prefix_base32_checksum format
# Example: WF_ABC123XY_Z
EUID_PATTERN = re.compile(r'^[A-Z]{2,4}_[A-Z0-9]{6,12}_[A-Z0-9]$')

# UUID pattern (standard UUID v4)
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def validate_euid(value: Any, field_name: str = "euid") -> bool:
    """
    Validate an EUID (External Unique Identifier).
    
    BLOOM EUIDs follow the pattern: PREFIX_BASE32_CHECKSUM
    Example: WF_ABC123XY_Z
    
    Args:
        value: Value to validate
        field_name: Name of the field for error messages
        
    Returns:
        True if valid
        
    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        raise ValidationError(field_name, value, "EUID cannot be None")
    
    if not isinstance(value, str):
        raise ValidationError(field_name, value, f"EUID must be a string, got {type(value).__name__}")
    
    if not value:
        raise ValidationError(field_name, value, "EUID cannot be empty")
    
    # Check basic format - must have at least 2 underscores
    parts = value.split('_')
    if len(parts) < 2:
        raise ValidationError(field_name, value, "EUID must contain at least one underscore separator")
    
    # Prefix should be uppercase letters
    prefix = parts[0]
    if not prefix.isalpha() or not prefix.isupper():
        raise ValidationError(field_name, value, f"EUID prefix must be uppercase letters, got '{prefix}'")
    
    return True


def validate_uuid(value: Any, field_name: str = "uuid") -> bool:
    """
    Validate a UUID.
    
    Args:
        value: Value to validate (string or UUID object)
        field_name: Name of the field for error messages
        
    Returns:
        True if valid
        
    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        raise ValidationError(field_name, value, "UUID cannot be None")
    
    # Handle UUID objects
    if isinstance(value, uuid_module.UUID):
        return True
    
    if not isinstance(value, str):
        raise ValidationError(field_name, value, f"UUID must be a string or UUID object, got {type(value).__name__}")
    
    try:
        uuid_module.UUID(value)
        return True
    except ValueError:
        raise ValidationError(field_name, value, f"Invalid UUID format: '{value}'")


def validate_json_addl(value: Any, field_name: str = "json_addl") -> bool:
    """
    Validate json_addl field structure.
    
    Args:
        value: Value to validate
        field_name: Name of the field for error messages
        
    Returns:
        True if valid
        
    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        return True  # None is acceptable for json_addl
    
    if not isinstance(value, dict):
        raise ValidationError(field_name, value, f"json_addl must be a dict, got {type(value).__name__}")
    
    return True


def validate_btype(value: Any, field_name: str = "btype") -> bool:
    """
    Validate btype field.

    Args:
        value: Value to validate
        field_name: Name of the field for error messages

    Returns:
        True if valid

    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        raise ValidationError(field_name, value, "btype cannot be None")

    if not isinstance(value, str):
        raise ValidationError(field_name, value, f"btype must be a string, got {type(value).__name__}")

    if not value:
        raise ValidationError(field_name, value, "btype cannot be empty")

    return True


def validate_not_empty(value: Any, field_name: str = "value") -> bool:
    """
    Validate that a value is not empty.

    Args:
        value: Value to validate
        field_name: Name of the field for error messages

    Returns:
        True if valid

    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        raise ValidationError(field_name, value, f"{field_name} cannot be None")

    if isinstance(value, str) and not value.strip():
        raise ValidationError(field_name, value, f"{field_name} cannot be empty")

    if isinstance(value, (list, dict)) and len(value) == 0:
        raise ValidationError(field_name, value, f"{field_name} cannot be empty")

    return True


def validate_positive_int(value: Any, field_name: str = "value") -> bool:
    """
    Validate that a value is a positive integer.

    Args:
        value: Value to validate
        field_name: Name of the field for error messages

    Returns:
        True if valid

    Raises:
        ValidationError: If validation fails
    """
    if value is None:
        raise ValidationError(field_name, value, f"{field_name} cannot be None")

    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(field_name, value, f"{field_name} must be an integer, got {type(value).__name__}")

    if value <= 0:
        raise ValidationError(field_name, value, f"{field_name} must be positive, got {value}")

    return True


def validated(**validators: Callable[[Any, str], bool]) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator to validate function arguments.

    Usage:
        @validated(euid=validate_euid, uuid=validate_uuid)
        def process_object(euid: str, uuid: str):
            ...

    Args:
        **validators: Mapping of argument names to validator functions

    Returns:
        Decorated function that validates arguments before execution
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Get function signature to map positional args to names
            import inspect
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())

            # Build dict of all arguments
            all_args = {}
            for i, arg in enumerate(args):
                if i < len(params):
                    all_args[params[i]] = arg
            all_args.update(kwargs)

            # Run validators
            for arg_name, validator in validators.items():
                if arg_name in all_args:
                    try:
                        validator(all_args[arg_name], arg_name)
                    except ValidationError:
                        raise
                    except Exception as e:
                        raise ValidationError(arg_name, all_args[arg_name], str(e))

            return func(*args, **kwargs)
        return wrapper
    return decorator


def validate_schema(data: Dict[str, Any], schema: Dict[str, Dict[str, Any]]) -> List[ValidationError]:
    """
    Validate a dictionary against a schema.

    Schema format:
        {
            "field_name": {
                "type": str,  # Expected type
                "required": True,  # Whether field is required
                "validator": validate_euid,  # Optional validator function
                "default": None,  # Default value if not provided
            }
        }

    Args:
        data: Dictionary to validate
        schema: Schema definition

    Returns:
        List of ValidationError objects (empty if valid)
    """
    errors = []

    for field_name, field_schema in schema.items():
        value = data.get(field_name)
        required = field_schema.get("required", False)
        expected_type = field_schema.get("type")
        validator = field_schema.get("validator")

        # Check required fields
        if required and value is None:
            errors.append(ValidationError(field_name, value, f"{field_name} is required"))
            continue

        # Skip validation for None values on optional fields
        if value is None:
            continue

        # Type check
        if expected_type and not isinstance(value, expected_type):
            errors.append(ValidationError(
                field_name, value,
                f"Expected {expected_type.__name__}, got {type(value).__name__}"
            ))
            continue

        # Custom validator
        if validator:
            try:
                validator(value, field_name)
            except ValidationError as e:
                errors.append(e)

    return errors

