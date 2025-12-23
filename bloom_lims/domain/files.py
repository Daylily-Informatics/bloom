"""
BLOOM LIMS Domain - Files

File management classes for handling file uploads, S3 storage, and file sets.
Extracted from bloom_lims/bobjs.py for better code organization.

Note: The full BloomFile implementation remains in bobjs.py due to its
complexity and S3 integration. This module provides class stubs and
additional helper classes.
"""

import logging
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


def _get_bloom_file():
    """Get BloomFile class from bobjs."""
    from bloom_lims.bobjs import BloomFile as _BF
    return _BF


def _get_base_class():
    """Get BloomObj base class lazily."""
    from bloom_lims.bobjs import BloomObj
    return BloomObj


class BloomFile:
    """
    File class for managing file uploads and S3 storage.
    
    This class provides file management functionality including:
    - Creating file records
    - Uploading to S3
    - Managing file metadata
    - Linking files to other objects
    
    The actual implementation is in bobjs.py. This class provides
    a clean interface.
    """
    
    _actual_class = None
    
    def __new__(cls, *args, **kwargs):
        if cls._actual_class is None:
            cls._actual_class = _get_bloom_file()
        # Return an instance of the actual class from bobjs
        return cls._actual_class(*args, **kwargs)


class BloomFileSet:
    """
    File Set class for managing collections of related files.
    
    A FileSet groups multiple files together, useful for:
    - Sequencing run outputs
    - Analysis results
    - Report packages
    """
    
    _base_class = None
    
    def __new__(cls, *args, **kwargs):
        if cls._base_class is None:
            cls._base_class = _get_base_class()
            if cls._base_class not in cls.__bases__:
                cls.__bases__ = (cls._base_class,) + cls.__bases__[1:] if len(cls.__bases__) > 1 else (cls._base_class,)
        return super().__new__(cls)
    
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb, is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)
    
    def create_file_set(
        self,
        name: str,
        description: Optional[str] = None,
        file_euids: Optional[List[str]] = None,
    ) -> Any:
        """
        Create a new file set.
        
        Args:
            name: Name for the file set
            description: Optional description
            file_euids: Optional list of file EUIDs to include
            
        Returns:
            Created file set object
        """
        # Create file set from template
        file_set = self.create_instance(
            self.query_template_by_component_v2(
                "file_set", "generic", "file-set", "1.0"
            )[0].euid,
            {"properties": {"name": name, "description": description or ""}},
        )
        self.session.commit()
        
        # Link files if provided
        if file_euids:
            for file_euid in file_euids:
                self.create_generic_instance_lineage_by_euids(file_set.euid, file_euid)
            self.session.commit()
        
        return file_set
    
    def add_file_to_set(self, file_set_euid: str, file_euid: str) -> None:
        """Add a file to a file set."""
        self.create_generic_instance_lineage_by_euids(file_set_euid, file_euid)
        self.session.commit()
    
    def get_files_in_set(self, file_set_euid: str) -> List[Any]:
        """Get all files in a file set."""
        file_set = self.get_by_euid(file_set_euid)
        if not file_set:
            return []
        
        files = []
        for lineage in file_set.parent_of_lineages:
            if lineage.child_instance.super_type == "file":
                files.append(lineage.child_instance)
        return files


class BloomFileReference:
    """
    File Reference class for managing references to external files.
    
    Used for files that are not stored in the BLOOM S3 buckets but
    need to be tracked in the system.
    """
    
    _base_class = None
    
    def __new__(cls, *args, **kwargs):
        if cls._base_class is None:
            cls._base_class = _get_base_class()
            if cls._base_class not in cls.__bases__:
                cls.__bases__ = (cls._base_class,) + cls.__bases__[1:] if len(cls.__bases__) > 1 else (cls._base_class,)
        return super().__new__(cls)
    
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb, is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)
    
    def create_reference(
        self,
        uri: str,
        reference_type: str = "external",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Create a reference to an external file.
        
        Args:
            uri: URI of the external file
            reference_type: Type of reference (external, s3, http, etc.)
            metadata: Additional metadata
            
        Returns:
            Created file reference object
        """
        properties = {
            "uri": uri,
            "reference_type": reference_type,
            **(metadata or {}),
        }
        
        file_ref = self.create_instance(
            self.query_template_by_component_v2(
                "file", "reference", "external", "1.0"
            )[0].euid,
            {"properties": properties},
        )
        self.session.commit()
        return file_ref

