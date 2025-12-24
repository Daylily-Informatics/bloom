"""
Pydantic schemas for file management in BLOOM LIMS (Dewey file system).

Files are managed objects that can be attached to other BLOOM objects
and stored in S3-compatible storage.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import Field, field_validator, HttpUrl

from .base import BloomBaseSchema, TimestampMixin, validate_euid


class FileBaseSchema(BloomBaseSchema):
    """Base schema for file objects."""
    
    name: str = Field(..., min_length=1, max_length=500, description="File name")
    file_type: str = Field(..., description="File type/extension")
    description: Optional[str] = Field(None, max_length=2000, description="File description")
    
    # File properties
    original_filename: Optional[str] = Field(None, max_length=500, description="Original filename")
    mime_type: Optional[str] = Field(None, max_length=200, description="MIME type")
    file_size_bytes: Optional[int] = Field(None, ge=0, description="File size in bytes")
    checksum: Optional[str] = Field(None, max_length=128, description="File checksum (SHA256)")
    
    # Metadata
    json_addl: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")
    tags: Optional[List[str]] = Field(None, description="File tags")
    
    @field_validator("file_type", mode="before")
    @classmethod
    def normalize_file_type(cls, v):
        if v:
            v = str(v).strip().lower()
            return v.lstrip('.')
        return v


class FileUploadSchema(FileBaseSchema):
    """Schema for file upload request."""
    
    # Upload configuration
    bucket_prefix: Optional[str] = Field(None, description="S3 bucket prefix")
    storage_class: str = Field(default="STANDARD", description="Storage class")
    
    # Association
    attach_to_euid: Optional[str] = Field(None, description="Object to attach file to")
    
    @field_validator("attach_to_euid", mode="before")
    @classmethod
    def validate_attach_euid(cls, v):
        if v is not None and str(v).strip():
            return validate_euid(v)
        return None


class FileResponseSchema(FileBaseSchema, TimestampMixin):
    """Schema for file API responses."""
    
    euid: str = Field(..., description="File EUID")
    uuid: str = Field(..., description="File UUID")
    status: str = Field(default="active", description="File status")
    is_deleted: bool = Field(default=False, description="Soft delete flag")
    
    # Storage info
    s3_key: Optional[str] = Field(None, description="S3 object key")
    s3_bucket: Optional[str] = Field(None, description="S3 bucket name")
    storage_location: Optional[str] = Field(None, description="Full storage path")
    
    # Access
    download_url: Optional[str] = Field(None, description="Pre-signed download URL")
    url_expires_at: Optional[datetime] = Field(None, description="URL expiration time")
    
    # Associations
    attached_to_euids: List[str] = Field(default_factory=list, description="Attached object EUIDs")
    file_set_euids: List[str] = Field(default_factory=list, description="File set EUIDs")
    
    # Upload info
    uploaded_by: Optional[str] = Field(None, description="Uploader user")


class FileSetBaseSchema(BloomBaseSchema):
    """Base schema for file sets."""
    
    name: str = Field(..., min_length=1, max_length=500, description="File set name")
    description: Optional[str] = Field(None, max_length=2000, description="Description")
    set_type: Optional[str] = Field(None, description="File set type")
    json_addl: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata")


class FileSetCreateSchema(FileSetBaseSchema):
    """Schema for creating a file set."""
    
    file_euids: List[str] = Field(default_factory=list, description="File EUIDs to include")
    
    @field_validator("file_euids", mode="before")
    @classmethod
    def validate_file_euids(cls, v):
        if v is None:
            return []
        return [validate_euid(euid) for euid in v if euid and str(euid).strip()]


class FileSetResponseSchema(FileSetBaseSchema, TimestampMixin):
    """Schema for file set API responses."""
    
    euid: str = Field(..., description="File set EUID")
    uuid: str = Field(..., description="File set UUID")
    status: str = Field(default="active", description="Status")
    
    file_count: int = Field(default=0, description="Number of files in set")
    total_size_bytes: int = Field(default=0, description="Total size of files")
    files: Optional[List[FileResponseSchema]] = Field(None, description="Files in set")


class FileReferenceSchema(BloomBaseSchema):
    """Schema for file reference (expiring links, external shares)."""
    
    file_euid: str = Field(..., description="File EUID")
    reference_type: str = Field(default="presigned", description="Reference type")
    
    # Access configuration
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800, description="Expiry time (60s-7d)")
    access_level: str = Field(default="read", pattern="^(read|write)$", description="Access level")
    
    # Optional constraints
    allowed_ips: Optional[List[str]] = Field(None, description="Allowed IP addresses")
    max_downloads: Optional[int] = Field(None, ge=1, description="Max download count")
    
    @field_validator("file_euid", mode="before")
    @classmethod
    def validate_file_euid(cls, v):
        return validate_euid(v)


class FileReferenceResponseSchema(BloomBaseSchema, TimestampMixin):
    """Schema for file reference response."""
    
    euid: str = Field(..., description="Reference EUID")
    file_euid: str = Field(..., description="File EUID")
    
    url: str = Field(..., description="Access URL")
    expires_at: datetime = Field(..., description="Expiration time")
    
    download_count: int = Field(default=0, description="Download count")
    is_expired: bool = Field(default=False, description="Whether reference is expired")


class FileSearchSchema(BloomBaseSchema):
    """Schema for file search parameters."""
    
    name_contains: Optional[str] = Field(None, description="Search by name")
    file_type: Optional[str] = Field(None, description="Filter by file type")
    mime_type: Optional[str] = Field(None, description="Filter by MIME type")
    min_size_bytes: Optional[int] = Field(None, ge=0, description="Minimum file size")
    max_size_bytes: Optional[int] = Field(None, ge=0, description="Maximum file size")
    uploaded_by: Optional[str] = Field(None, description="Filter by uploader")
    uploaded_after: Optional[datetime] = Field(None, description="Uploaded after date")
    uploaded_before: Optional[datetime] = Field(None, description="Uploaded before date")
    tags: Optional[List[str]] = Field(None, description="Filter by tags (any match)")
    attached_to_euid: Optional[str] = Field(None, description="Filter by attached object")

