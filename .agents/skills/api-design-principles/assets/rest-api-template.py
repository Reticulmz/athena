"""FastAPI による REST API template.

Pagination, filtering, error handling, security middleware を含む実用的な API skeleton を示す.

Notes:
    Project 固有の認証, 永続化, origin policy は利用先で差し替える.
"""

import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

app = FastAPI(title="API Template", version="1.0.0", docs_url="/api/docs")


def _csv_env(name: str, default: str) -> list[str]:
    """環境変数の comma-separated value を空要素なしの list へ変換する.

    Args:
        name (str): 参照する環境変数名.
        default (str): 環境変数が未設定の場合に使う comma-separated value.

    Returns:
        list[str]: 前後の空白と空要素を除いた値の list.
    """
    values = os.getenv(name, default)
    return [value.strip() for value in values.split(",") if value.strip()]


ALLOWED_HOSTS = _csv_env("ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_ORIGINS = _csv_env("ALLOWED_ORIGINS", "http://localhost:3000")

# Security Middleware
# Trusted Host: Prevents HTTP Host Header attacks
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS,
)

# CORS: Configures Cross-Origin Resource Sharing
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Set True only when cookies/auth headers are needed and origins are restricted.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Models
class UserStatus(StrEnum):
    """User account status の template enum を表す.

    Attributes:
        ACTIVE (UserStatus): 利用可能な account status.
        INACTIVE (UserStatus): 利用停止中の account status.
        SUSPENDED (UserStatus): 制限中の account status.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class UserBase(BaseModel):
    """User 作成と更新で共有する入力 fields を表す.

    Attributes:
        email (EmailStr): User の連絡先 email address.
        name (str): 1文字以上100文字以下の表示名.
        status (UserStatus): account の現在 status.
    """

    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)
    status: UserStatus = UserStatus.ACTIVE


class UserCreate(UserBase):
    """User 作成 request body を表す.

    Attributes:
        email (EmailStr): 作成する User の連絡先 email address.
        name (str): 作成する User の表示名.
        status (UserStatus): 作成直後の account status.
        password (str): 8文字以上の初期 password.
    """

    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    """User 部分更新 request body を表す.

    Attributes:
        email (EmailStr | None): 更新後の email address. フィールドを省略した場合のみ変更しない.
            明示的に `None` を指定した場合は `None` へ更新する.
        name (str | None): 更新後の表示名. フィールドを省略した場合のみ変更しない.
            明示的に `None` を指定した場合は `None` へ更新する.
        status (UserStatus | None): 更新後の account status.
            フィールドを省略した場合のみ変更しない.
            明示的に `None` を指定した場合は `None` へ更新する.
    """

    email: EmailStr | None = None
    name: str | None = Field(None, min_length=1, max_length=100)
    status: UserStatus | None = None


class User(UserBase):
    """User response model を表す.

    Attributes:
        email (EmailStr): User の連絡先 email address.
        name (str): User の表示名.
        status (UserStatus): account の現在 status.
        user_id (str): response では JSON field `id` として出力する user identifier.
        created_at (datetime): User 作成日時.
        updated_at (datetime): User 更新日時.
        model_config (ConfigDict): ORM attribute と field alias を有効にする Pydantic config.
    """

    user_id: str = Field(alias="id")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# Pagination
class PaginationParams(BaseModel):
    """Pagination query parameters を表す.

    Attributes:
        page (int): 1始まりの取得 page number.
        page_size (int): 1 page あたりの取得 item 数. 最大値は100.
    """

    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class PaginatedResponse(BaseModel):
    """Paginated list response を表す.

    Attributes:
        items (list[Any]): 現在 page に含まれる response item.
        total (int): response が表す item 総数.
            この template の mock endpoint は filtering の有無にかかわらず `100` を設定する.
        page (int): 現在の1始まり page number.
        page_size (int): 1 page あたりの item 数.
        pages (int): total と page_size から計算した page 総数.
    """

    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int


# Error handling
class ErrorDetail(BaseModel):
    """Field 単位の error detail を表す.

    Attributes:
        field (str | None): error に対応する request field. 全体 error の場合は None.
        message (str): 利用者へ表示する error の説明.
        code (str): client が分岐に使う machine-readable error code.
    """

    field: str | None = None
    message: str
    code: str


class ErrorResponse(BaseModel):
    """API error response body を表す.

    Attributes:
        error (str): error category を示す短い名前.
        message (str): error の利用者向け説明.
        details (list[ErrorDetail] | None): field 単位の detail. 存在しない場合は None.
    """

    error: str
    message: str
    details: list[ErrorDetail] | None = None


def _error_name(detail: Any, fallback: str) -> str:
    """HTTPException detail から error category を取り出す.

    Args:
        detail (Any): HTTPException に設定された detail value.
        fallback (str): detail に文字列の error field がない場合に返す名前.

    Returns:
        str: detail の error field, または fallback.
    """
    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, str):
            return error
    return fallback


def _error_message(detail: Any) -> str:
    """HTTPException detail から表示用 error message を取り出す.

    Args:
        detail (Any): HTTPException に設定された detail value.

    Returns:
        str: detail 自身または message field の文字列. 取得できない場合は `Error`.
    """
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str):
            return message
    return "Error"


def _error_details(detail: Any) -> list[ErrorDetail] | None:
    """HTTPException detail の field detail を ErrorDetail list へ変換する.

    Args:
        detail (Any): HTTPException に設定された detail value.

    Returns:
        list[ErrorDetail] | None: 有効な detail list. 未指定または不正な値の場合は None.
    """
    if not isinstance(detail, dict):
        return None

    raw_details = detail.get("details")
    if not isinstance(raw_details, list):
        return None

    details: list[ErrorDetail] = []
    for raw_detail in raw_details:
        if isinstance(raw_detail, ErrorDetail):
            details.append(raw_detail)
        elif isinstance(raw_detail, dict):
            try:
                details.append(ErrorDetail.model_validate(raw_detail))
            except ValueError:
                return None
        else:
            return None
    return details


@app.exception_handler(HTTPException)
async def http_exception_handler(_request, exc):
    """HTTPException を共通 error response に変換する.

    Args:
        _request (Request): FastAPI から渡される request object. この template では参照しない.
        exc (HTTPException): 変換対象の exception.

    Returns:
        JSONResponse: status code と標準化した error body を保持する response.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=_error_name(exc.detail, exc.__class__.__name__),
            message=_error_message(exc.detail),
            details=_error_details(exc.detail),
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
    """User 一覧を pagination と filtering 付きで返す.

    Args:
        page (int): 1始まりの page number.
        page_size (int): 1 page あたりの item 数.
        status_filter (UserStatus | None): optional account status filter. Query name は `status`.
        search (str | None): optional name substring filter.

    Returns:
        PaginatedResponse: items に User response dict を含む pagination result.

    Notes:
        この template の mock は filtering 後の items だけを絞り込み, total と pages は固定の全件数
        `100` を基に返す.
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
    """User を作成する.

    Args:
        user (UserCreate): 作成する User の request body.

    Returns:
        User: 作成された User response model.
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
    """User ID で User を取得する.

    Args:
        user_id (str): 取得対象の User identifier.

    Returns:
        User: 取得された User response model.

    Raises:
        HTTPException: User が見つからない場合.
    """
    # Mock: Check if exists
    if user_id == "999":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "not_found",
                "message": "User not found",
                "details": [
                    {
                        "field": "id",
                        "message": f"User {user_id} was not found",
                        "code": "not_found",
                    },
                ],
            },
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
    """User を部分更新する.

    Args:
        user_id (str): 更新対象の User identifier.
        update (UserUpdate): 更新する fields.

    Returns:
        User: 更新後の User response model.

    Raises:
        HTTPException: User が見つからない場合.
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
    """User を削除する.

    Args:
        user_id (str): 削除対象の User identifier.

    Returns:
        None: HTTP 204 response として扱う.

    Raises:
        HTTPException: User が見つからない場合.
    """
    await get_user(user_id)  # Verify exists


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
