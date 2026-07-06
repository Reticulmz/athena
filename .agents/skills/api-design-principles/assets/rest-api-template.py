"""FastAPI による REST API template。

Pagination、filtering、error handling、security middleware を含む
実用的な API skeleton を示す。

Constraints:
    Project 固有の認証、永続化、origin policy は利用先で差し替える。
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
    allowed_hosts=["*"],  # Example policy: restrict to ["api.example.com"] in production
)

# CORS: Configures Cross-Origin Resource Sharing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Example policy: use specific origins in production
    # Set True only when cookies/auth headers are needed and origins are restricted.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Models
class UserStatus(StrEnum):
    """User account status の template enum。"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class UserBase(BaseModel):
    """User 作成/更新で共有する入力 fields。"""

    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    status: UserStatus = UserStatus.ACTIVE


class UserCreate(UserBase):
    """User 作成 request body。"""

    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    """User 部分更新 request body。"""

    email: EmailStr | None = None
    name: str | None = Field(None, min_length=1, max_length=100)
    status: UserStatus | None = None


class User(UserBase):
    """User response model。

    Attributes:
        user_id: Response では JSON field `id` として出力する user identifier。
        created_at: User 作成日時。
        updated_at: User 更新日時。
    """

    user_id: str = Field(alias="id")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# Pagination
class PaginationParams(BaseModel):
    """Pagination query parameters。"""

    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class PaginatedResponse(BaseModel):
    """Paginated list response。"""

    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int


# Error handling
class ErrorDetail(BaseModel):
    """Field 単位の error detail。"""

    field: str | None = None
    message: str
    code: str


class ErrorResponse(BaseModel):
    """API error response body。"""

    error: str
    message: str
    details: list[ErrorDetail] | None = None


@app.exception_handler(HTTPException)
async def http_exception_handler(_request, exc):
    """HTTPException を共通 error response に変換する。

    Args:
        _request: FastAPI から渡される request object。この template では参照しない。
        exc: 変換対象の HTTPException。

    Returns:
        JSONResponse。status code と error body を保持する。
    """
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
    """User 一覧を pagination/filtering 付きで返す。

    Args:
        page: 1 始まりの page number。
        page_size: 1 page あたりの item 数。
        status_filter: Optional account status filter。Query name は `status`。
        search: Optional name substring filter。

    Returns:
        PaginatedResponse。items には User response dict を含める。
    """
    # Mock implementation
    total = 100
    items = [
        User(
            user_id=str(i),
            email=f"user{i}@example.com",
            name=f"User {i}",
            status=UserStatus.ACTIVE,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ).model_dump(by_alias=True)
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
    """User を作成する。

    Args:
        user: 作成する user の request body。

    Returns:
        作成された User response model。
    """
    # Mock implementation
    return User(
        user_id="123",
        email=user.email,
        name=user.name,
        status=user.status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@app.get("/api/users/{user_id}", response_model=User, tags=["Users"])
async def get_user(user_id: str = Path(..., description="User ID")):
    """User ID で user を取得する。

    Args:
        user_id: 取得対象の user identifier。

    Returns:
        User response model。

    Raises:
        HTTPException: User が見つからない場合。
    """
    # Mock: Check if exists
    if user_id == "999":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "User not found", "details": {"id": user_id}},
        )

    return User(
        user_id=user_id,
        email="user@example.com",
        name="User Name",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@app.patch("/api/users/{user_id}", response_model=User, tags=["Users"])
async def update_user(user_id: str, update: UserUpdate):
    """User を部分更新する。

    Args:
        user_id: 更新対象の user identifier。
        update: 更新する fields。

    Returns:
        更新後の User response model。

    Raises:
        HTTPException: User が見つからない場合。
    """
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
    """User を削除する。

    Args:
        user_id: 削除対象の user identifier。

    Returns:
        None。HTTP 204 response として扱う。

    Raises:
        HTTPException: User が見つからない場合。
    """
    await get_user(user_id)  # Verify exists


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
