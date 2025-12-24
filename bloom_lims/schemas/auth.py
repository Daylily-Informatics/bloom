"""
Pydantic schemas for authentication and user management in BLOOM LIMS.
"""

import re
from datetime import datetime
from typing import List, Optional
from pydantic import Field, field_validator, EmailStr

from .base import BloomBaseSchema, TimestampMixin


# Email validation pattern
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class AuthLoginSchema(BloomBaseSchema):
    """Schema for user login request."""
    
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password")
    remember_me: bool = Field(default=False, description="Extended session")
    
    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, v):
        """Validate and normalize email."""
        if v:
            v = str(v).strip().lower()
            if not EMAIL_PATTERN.match(v):
                raise ValueError("Invalid email format")
        return v


class AuthTokenSchema(BloomBaseSchema):
    """Schema for authentication token response."""
    
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiry in seconds")
    refresh_token: Optional[str] = Field(None, description="Refresh token")
    
    # User info
    user_id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    roles: List[str] = Field(default_factory=list, description="User roles")


class UserBaseSchema(BloomBaseSchema):
    """Base schema for user data."""
    
    email: str = Field(..., description="User email address")
    name: Optional[str] = Field(None, max_length=200, description="User display name")
    first_name: Optional[str] = Field(None, max_length=100, description="First name")
    last_name: Optional[str] = Field(None, max_length=100, description="Last name")
    
    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, v):
        """Validate and normalize email."""
        if v:
            v = str(v).strip().lower()
            if not EMAIL_PATTERN.match(v):
                raise ValueError("Invalid email format")
        return v
    
    @property
    def display_name(self) -> str:
        """Get user display name."""
        if self.name:
            return self.name
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        if self.first_name:
            return self.first_name
        return self.email.split("@")[0]


class UserCreateSchema(UserBaseSchema):
    """Schema for creating a new user."""
    
    password: str = Field(..., min_length=8, max_length=100, description="User password")
    confirm_password: str = Field(..., description="Password confirmation")
    roles: List[str] = Field(default=["user"], description="User roles")
    
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v):
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v
    
    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        """Validate passwords match."""
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class UserUpdateSchema(BloomBaseSchema):
    """Schema for updating user data."""
    
    name: Optional[str] = Field(None, max_length=200, description="User display name")
    first_name: Optional[str] = Field(None, max_length=100, description="First name")
    last_name: Optional[str] = Field(None, max_length=100, description="Last name")
    is_active: Optional[bool] = Field(None, description="Account active flag")
    roles: Optional[List[str]] = Field(None, description="User roles")


class UserSchema(UserBaseSchema, TimestampMixin):
    """Schema for user API responses."""
    
    id: str = Field(..., description="User ID")
    uuid: Optional[str] = Field(None, description="User UUID")
    is_active: bool = Field(default=True, description="Account active flag")
    is_verified: bool = Field(default=False, description="Email verified flag")
    roles: List[str] = Field(default_factory=list, description="User roles")
    
    # Session info
    last_login: Optional[datetime] = Field(None, description="Last login timestamp")
    login_count: int = Field(default=0, description="Total login count")
    
    # Preferences
    preferences: dict = Field(default_factory=dict, description="User preferences")


class PasswordResetRequestSchema(BloomBaseSchema):
    """Schema for password reset request."""
    
    email: str = Field(..., description="User email address")
    
    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, v):
        """Validate and normalize email."""
        if v:
            v = str(v).strip().lower()
            if not EMAIL_PATTERN.match(v):
                raise ValueError("Invalid email format")
        return v


class PasswordResetSchema(BloomBaseSchema):
    """Schema for password reset completion."""
    
    token: str = Field(..., description="Reset token")
    new_password: str = Field(..., min_length=8, description="New password")
    confirm_password: str = Field(..., description="Password confirmation")
    
    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v):
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v

