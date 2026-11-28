"""Authentication and document access control (M7).

- Passwords are stored as bcrypt hashes (slow on purpose, salted), never in plain text.
- Login returns a JWT: a signed token holding the user's id, role and access levels. The API verifies the
  signature on every request instead of looking the session up in a database: stateless, so any number of
  API replicas can serve any user.
- Access control: each document has an `access_level`; each user has the levels they may read. Retrieval only
  searches allowed documents, so a user can never be *shown* text they're not cleared for, not even by the LLM.
- AUTH_REQUIRED=false (local dev) lets anonymous requests through as an "analyst" with public access.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import HTTPException, Request

ALGORITHM = "HS256"


@dataclass
class User:
    id: str | None
    email: str
    role: str
    access_levels: list[str]
    entity_type: str | None = None


ANONYMOUS = User(id=None, email="anonymous", role="analyst", access_levels=["public"])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user: User, secret: str, ttl_minutes: int) -> str:
    now = datetime.now(UTC)
    claims = {"sub": user.id, "email": user.email, "role": user.role, "acl": user.access_levels,
              "entity": user.entity_type, "iat": now, "exp": now + timedelta(minutes=ttl_minutes)}
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> User:
    try:
        c = jwt.decode(token, secret, algorithms=[ALGORITHM])   # verifies signature AND expiry
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid or expired token ({type(exc).__name__})") from exc
    return User(id=c["sub"], email=c["email"], role=c["role"], access_levels=c["acl"], entity_type=c.get("entity"))


def current_user(request: Request) -> User:
    """FastAPI dependency: the logged-in user, or ANONYMOUS when auth isn't required."""
    settings = request.app.state.settings
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return decode_token(header[7:], settings.jwt_secret)
    if settings.auth_required:
        raise HTTPException(401, "login required", headers={"WWW-Authenticate": "Bearer"})
    return ANONYMOUS


def require_admin(user: User) -> User:
    if user.role != "admin":
        raise HTTPException(403, "admin only")
    return user


async def authenticate(conn, email: str, password: str) -> User | None:
    row = await conn.fetchrow("SELECT id, email, password_hash, role, access_levels, entity_type FROM users "
                              "WHERE email = $1", email.lower())
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return User(str(row["id"]), row["email"], row["role"], list(row["access_levels"]), row["entity_type"])
