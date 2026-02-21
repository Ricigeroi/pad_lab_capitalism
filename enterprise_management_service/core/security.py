from typing import Optional

import bcrypt
from jose import JWTError, jwt

from core.config import settings


def decode_access_token(token: str) -> Optional[str]:
    """Decode a JWT and return the subject (user_id as string), or None if invalid."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
