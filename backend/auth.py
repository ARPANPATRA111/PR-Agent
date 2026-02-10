import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import jwt
from passlib.context import CryptContext

from config import settings

logger = logging.getLogger(__name__)

SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

security = HTTPBearer(auto_error=False)


class Token(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60


class TokenData(BaseModel):
    user_id: Optional[int] = None
    telegram_id: Optional[int] = None
    username: Optional[str] = None
    exp: Optional[datetime] = None
    token_type: str = "access"


class UserCredentials(BaseModel):
    telegram_id: int
    verification_code: Optional[str] = None


class AuthResponse(BaseModel):
    success: bool
    message: str
    token: Optional[Token] = None
    user: Optional[dict] = None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh"
    })
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_tokens(
    user_id: int,
    telegram_id: int,
    username: Optional[str] = None
) -> Token:
    token_data = {
        "sub": str(user_id),
        "telegram_id": telegram_id,
        "username": username
    }
    
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


def verify_token(token: str, expected_type: str = "access") -> TokenData:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        token_type = payload.get("type", "access")
        if token_type != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token type. Expected {expected_type}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return TokenData(
            user_id=int(user_id),
            telegram_id=payload.get("telegram_id"),
            username=payload.get("username"),
            exp=datetime.fromtimestamp(payload.get("exp")),
            token_type=token_type
        )
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> TokenData:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return verify_token(credentials.credentials, "access")


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[TokenData]:
    if not credentials:
        return None
    
    try:
        return verify_token(credentials.credentials, "access")
    except HTTPException:
        return None


async def get_telegram_user_id_from_token(
    user: TokenData = Depends(get_current_user)
) -> int:
    if not user.telegram_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token does not contain Telegram user ID"
        )
    return user.telegram_id


_verification_codes: dict = {}


def generate_verification_code(telegram_id: int) -> str:
    import random
    import string
    
    code = ''.join(random.choices(string.digits, k=6))
    
    _verification_codes[telegram_id] = {
        "code": code,
        "expires": datetime.utcnow() + timedelta(minutes=5)
    }
    
    logger.info(f"Generated verification code for Telegram ID {telegram_id}")
    return code


def verify_telegram_code(telegram_id: int, code: str) -> bool:
    stored = _verification_codes.get(telegram_id)
    
    if not stored:
        return False
    
    if datetime.utcnow() > stored["expires"]:
        del _verification_codes[telegram_id]
        return False
    
    if stored["code"] == code:
        del _verification_codes[telegram_id]
        return True
    
    return False


def cleanup_expired_codes():
    now = datetime.utcnow()
    expired = [
        tid for tid, data in _verification_codes.items()
        if now > data["expires"]
    ]
    for tid in expired:
        del _verification_codes[tid]


class APIKeyAuth:
    
    def __init__(self, api_keys: list):
        self.api_keys = set(api_keys)
    
    async def __call__(self, request: Request) -> bool:
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key not in self.api_keys:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key"
            )
        return True
