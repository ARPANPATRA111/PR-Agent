import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
SESSION_TOKEN_TYPE = "session"
SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer(auto_error=False)


class Token(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = settings.session_max_age_seconds


class TokenData(BaseModel):
    user_id: int
    telegram_id: int
    username: Optional[str] = None
    csrf_token: str
    exp: datetime
    token_type: str = SESSION_TOKEN_TYPE
    auth_source: str = "bearer"


class AuthResponse(BaseModel):
    success: bool
    message: str
    csrf_token: str
    expires_in: int
    user: Dict[str, Any]


class TelegramMiniAppAuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def _signing_secret() -> str:
    secret = settings.effective_session_signing_secret
    if not secret:
        raise RuntimeError("Session signing secret is not configured")
    return secret


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(seconds=settings.session_max_age_seconds)
    )
    to_encode = data.copy()
    to_encode.setdefault("csrf", secrets.token_urlsafe(32))
    to_encode.update({
        "exp": expire,
        "iat": now,
        "type": SESSION_TOKEN_TYPE,
        "jti": secrets.token_urlsafe(18),
    })
    return jwt.encode(to_encode, _signing_secret(), algorithm=ALGORITHM)


def create_tokens(
    user_id: int,
    telegram_id: int,
    username: Optional[str] = None,
) -> Token:
    csrf_token = secrets.token_urlsafe(32)
    access_token = create_access_token({
        "sub": str(user_id),
        "telegram_id": telegram_id,
        "username": username,
        "csrf": csrf_token,
    })
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.session_max_age_seconds,
    )


def create_session(
    user_id: int,
    telegram_id: int,
    username: Optional[str] = None,
) -> tuple[str, str]:
    csrf_token = secrets.token_urlsafe(32)
    token = create_access_token({
        "sub": str(user_id),
        "telegram_id": telegram_id,
        "username": username,
        "csrf": csrf_token,
    })
    return token, csrf_token


def verify_token(token: str, expected_type: str = SESSION_TOKEN_TYPE) -> TokenData:
    try:
        payload = jwt.decode(token, _signing_secret(), algorithms=[ALGORITHM])
        token_type = payload.get("type")
        if token_type != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid session",
            )

        user_id = payload.get("sub")
        telegram_id = payload.get("telegram_id")
        csrf_token = payload.get("csrf")
        expires_at = payload.get("exp")
        if not user_id or not telegram_id or not csrf_token or not expires_at:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid session",
            )

        return TokenData(
            user_id=int(user_id),
            telegram_id=int(telegram_id),
            username=payload.get("username"),
            csrf_token=str(csrf_token),
            exp=datetime.fromtimestamp(float(expires_at), tz=timezone.utc),
            token_type=token_type,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        ) from exc
    except (jwt.InvalidTokenError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        ) from exc


def validate_telegram_init_data(
    init_data: str,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram authentication is not configured",
        )

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram authentication data",
        ) from exc

    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram authentication data",
        )

    values = dict(pairs)
    provided_hash = values.pop("hash", "")
    if len(provided_hash) != 64:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram authentication data",
        )

    data_check_string = "\n".join(
        f"{key}={values[key]}" for key in sorted(values)
    )
    secret_key = hmac.new(
        b"WebAppData",
        settings.telegram_bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, provided_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram authentication data",
        )

    try:
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
        telegram_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram authentication data",
        ) from exc

    current_time = now or datetime.now(timezone.utc)
    age_seconds = current_time.timestamp() - auth_date
    if age_seconds < -30 or age_seconds > settings.telegram_auth_max_age_seconds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Telegram authentication data expired",
        )
    if telegram_id <= 0 or user.get("is_bot") is True:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram user",
        )

    return {
        "telegram_id": telegram_id,
        "first_name": str(user.get("first_name") or "User")[:255],
        "last_name": (
            str(user["last_name"])[:255]
            if user.get("last_name") is not None
            else None
        ),
        "username": (
            str(user["username"])[:255]
            if user.get("username") is not None
            else None
        ),
        "language_code": (
            str(user["language_code"])[:32]
            if user.get("language_code") is not None
            else None
        ),
    }


def authenticate_request(request: Request) -> TokenData:
    cookie_token = request.cookies.get(settings.session_cookie_name)
    authorization = request.headers.get("Authorization", "")
    bearer_token = (
        authorization[7:].strip()
        if authorization.lower().startswith("bearer ")
        else None
    )
    token = cookie_token or bearer_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user = verify_token(token)
    user.auth_source = "cookie" if cookie_token else "bearer"

    if request.method.upper() not in SAFE_HTTP_METHODS and cookie_token:
        csrf_header = request.headers.get("X-CSRF-Token", "")
        if not csrf_header or not hmac.compare_digest(
            csrf_header,
            user.csrf_token,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed",
            )

    return user


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    del credentials
    existing = getattr(request.state, "current_user", None)
    if existing is not None:
        return existing
    return authenticate_request(request)


async def get_current_user_optional(
    request: Request,
) -> Optional[TokenData]:
    try:
        return authenticate_request(request)
    except HTTPException:
        return None


async def get_telegram_user_id_from_token(
    user: TokenData = Depends(get_current_user),
) -> int:
    return user.telegram_id
