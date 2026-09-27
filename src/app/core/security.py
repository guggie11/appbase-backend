"""Security utilities: JWT encode/decode with JTI, Argon2 password hashing, token helpers."""
import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import settings

pwd_hash = PasswordHash([Argon2Hasher()])


def hash_password(plain: str) -> str:
    return pwd_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_hash.verify(plain, hashed)


def create_access_token(subject: str | Any, expires_delta: timedelta | None = None) -> tuple[str, str]:
    """Return (jwt_string, jti)."""
    jti = str(uuid.uuid4())
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": str(subject),
        "exp": expire,
        "type": "access",
        "jti": jti,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti


def create_raw_refresh_token() -> tuple[str, str]:
    """Return (raw_token_hex, sha256_hash)."""
    raw = os.urandom(32)
    raw_hex = raw.hex()
    token_hash = hashlib.sha256(raw.hex().encode()).hexdigest()
    return raw_hex, token_hash


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        raise ValueError("Invalid token") from e
