"""
Production-ready REST API template using FastAPI.
Includes pagination, filtering, error handling, and best practices.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

app = FastAPI(title="API Template", version="1.0.0", docs_url="/api/docs")

# Security Middleware
# Trusted Host: Prevents HTTP Host Header attacks
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],  # TODO: Configure this in production, e.g. ["api.example.com"]
)

# CORS: Configures Cross-Origin Resource Sharing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Update this with specific origins in production
    # TODO: Set to True if you need cookies/auth headers, but restrict origins
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Models
class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class UserBase(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    status: UserStatus = UserStatus.ACTIVE


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    name: str | None = Field(None, min_length=1, max_length=100)
    status: UserStatus | None = None


class User(UserBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Pagination
class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int


# Error handling
class ErrorDetail(BaseModel):
    field: str | None = None
    message: str
    code: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: list[ErrorDetail] | None = None


@app.exception_handler(HTTPException)
async def http_exception_handler(_request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.__class__.__name__,
            message=exc.detail
            if isinstance(exc.detail, str)
            else exc.detail.get("message", "Error"),
            details=exc.detail.get("details") if isinstance(exc.detail, dict) else None,
        ).model_dump(),
    )


# Endpoints
@app.get("/api/users", response_model=PaginatedResponse, tags=["Users"])
async def list_users(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[UserStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query()] = None,
):
    """List users with pagination and filtering."""
    # Mock implementation
    total = 100
    items = [
        User(
            id=str(i),
            email=f"user{i}@example.com",
            name=f"User {i}",
            status=UserStatus.ACTIVE,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ).model_dump()
        for i in range((page - 1) * page_size, min(page * page_size, total))
    ]
    if status_filter is not None:
        items = [item for item in items if item["status"] == status_filter]
    if search:
        items = [item for item in items if search.lower() in item["name"].lower()]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@app.post("/api/users", response_model=User, status_code=status.HTTP_201_CREATED, tags=["Users"])
async def create_user(user: UserCreate):
    """Create a new user."""
    # Mock implementation
    return User(
        id="123",
        email=user.email,
        name=user.name,
        status=user.status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@app.get("/api/users/{user_id}", response_model=User, tags=["Users"])
async def get_user(user_id: str = Path(..., description="User ID")):
    """Get user by ID."""
    # Mock: Check if exists
    if user_id == "999":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found", "details": {"id": user_id}},
        )

    return User(
        id=user_id,
        email="user@example.com",
        name="User Name",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@app.patch("/api/users/{user_id}", response_model=User, tags=["Users"])
async def update_user(user_id: str, update: UserUpdate):
    """Partially update user."""
    # Validate user exists
    existing = await get_user(user_id)

    # Apply updates
    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(existing, field, value)

    existing.updated_at = datetime.now(UTC)
    return existing


@app.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Users"])
async def delete_user(user_id: str):
    """Delete user."""
    await get_user(user_id)  # Verify exists


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
