"""JWT 令牌与密码哈希工具。

安全约定：
* 密码使用 bcrypt 加盐哈希，数据库中绝不存明文；
* JWT 使用 HS256 对称签名，密钥来自 .env 的 ``JWT_SECRET``；
* Token 里只放 ``sub``（用户名）与 ``role``，不放入敏感信息。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# bcrypt 只处理前 72 字节，超出部分会被静默截断，这里显式截断避免「同一前缀密码等价」
_BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """JWT 解析失败（过期、签名错误、格式非法）。"""


def hash_password(plain_password: str) -> str:
    """对明文密码做 bcrypt 哈希。

    Args:
        plain_password: 明文密码。

    Returns:
        哈希后的密码字符串。
    """
    raw = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希是否匹配。

    Args:
        plain_password: 明文密码。
        hashed_password: 数据库中的哈希值。

    Returns:
        是否匹配。
    """
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES], hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError) as exc:
        logger.warning("密码校验异常: {}", exc)
        return False


def create_access_token(
    subject: str,
    role: str = "member",
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """签发 JWT。

    Args:
        subject: 用户名，写入 ``sub``。
        role: 用户角色。
        expires_minutes: 过期分钟数，默认取配置。
        extra_claims: 额外声明。

    Returns:
        编码后的 JWT 字符串。
    """
    expire_minutes = expires_minutes or settings.jwt_expire_minutes
    issued_at = datetime.now()
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(minutes=expire_minutes)).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """解析并校验 JWT。

    Args:
        token: JWT 字符串。

    Returns:
        解码后的载荷。

    Raises:
        TokenError: 令牌无效或已过期。
    """
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise TokenError(f"令牌无效或已过期: {exc}") from exc
