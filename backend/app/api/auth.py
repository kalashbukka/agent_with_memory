"""MVP auth: registered users (PBKDF2-hashed passwords) and opaque bearer tokens in SQLite.

Every user gets a stable user_id and their own isolated Hindsight memory bank.
"""

import hashlib
import hmac
import logging
import secrets
import sqlite3
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.db import connect, now_iso
from app.hindsight import client as hindsight
from app.hindsight.client import HindsightError
from app.hindsight.preferences import load_profile

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)

PBKDF2_ITERATIONS = 200_000


@dataclass(frozen=True)
class User:
    id: str
    username: str
    bank_id: str  # this user's private Hindsight memory bank


class Credentials(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=200)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class AuthResponse(BaseModel):
    token: str
    user_id: str
    username: str


# ---------------------------------------------------------------- helpers


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    except ValueError:
        return False
    return hmac.compare_digest(candidate, digest)


def user_bank_id(user_id: str) -> str:
    return f"{get_settings().hindsight_bank_id}-u-{user_id}"


def _create_user(conn: sqlite3.Connection, username: str, password: str, bank_id: str | None = None) -> User:
    user_id = uuid.uuid4().hex
    bank = bank_id or user_bank_id(user_id)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, hindsight_bank_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, hash_password(password), bank, now_iso()),
    )
    return User(user_id, username, bank)


def _new_session(conn: sqlite3.Connection, user: User) -> AuthResponse:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token, username, user_id, created_at) VALUES (?, ?, ?, ?)",
        (token, user.username, user.id, now_iso()),
    )
    return AuthResponse(token=token, user_id=user.id, username=user.username)


def migrate_legacy_demo_user() -> None:
    """One-time migration from the single-demo-login version of the app.

    Incidents created before isolation existed have created_by=<DEMO_USERNAME> and no user_id,
    and their memories live in the original bank HINDSIGHT_BANK_ID, written only by that account.
    Turn that account into a real user who owns those incidents and that bank. Other users each
    get a fresh bank. Nothing is deleted.
    """
    s = get_settings()
    with connect() as conn:
        legacy = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE user_id IS NULL AND created_by = ?", (s.demo_username,)
        ).fetchone()[0]
        if not legacy:
            return
        row = conn.execute("SELECT id FROM users WHERE username = ?", (s.demo_username,)).fetchone()
        if row is None:
            bank_taken = conn.execute("SELECT 1 FROM users WHERE hindsight_bank_id = ?", (s.hindsight_bank_id,)).fetchone()
            if bank_taken or not s.demo_password:
                return
            user_id = _create_user(conn, s.demo_username, s.demo_password, bank_id=s.hindsight_bank_id).id
        else:
            user_id = row["id"]
        conn.execute(
            "UPDATE incidents SET user_id = ? WHERE user_id IS NULL AND created_by = ?", (user_id, s.demo_username)
        )
        log.info("Migrated %d legacy incidents to user '%s'", legacy, s.demo_username)


# ---------------------------------------------------------------- routes


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(body: Credentials) -> AuthResponse:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (body.username,)).fetchone():
            raise HTTPException(status.HTTP_409_CONFLICT, "Username is already taken")
        user = _create_user(conn, body.username, body.password)
        session = _new_session(conn, user)
    # Create the user's private, empty memory bank (reads of a missing bank would 404).
    await hindsight.ensure_bank(user.bank_id)
    return session


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest) -> AuthResponse:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (body.username,)).fetchone()
        # Verify against a dummy hash when the user doesn't exist to keep timing uniform.
        ok = verify_password(body.password, row["password_hash"] if row else hash_password("x"))
        if row is None or not ok:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
        user = User(row["id"], row["username"], row["hindsight_bank_id"])
        session = _new_session(conn, user)
    await hindsight.ensure_bank(user.bank_id)
    return session


@router.post("/logout", status_code=204)
def logout(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    if creds:
        with connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (creds.credentials,))


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    with connect() as conn:
        row = conn.execute(
            """SELECT u.id, u.username, u.hindsight_bank_id FROM sessions s
               JOIN users u ON u.id = s.user_id WHERE s.token = ?""",
            (creds.credentials,),
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again")
    return User(row["id"], row["username"], row["hindsight_bank_id"])


@router.get("/me")
async def me(user: User = Depends(current_user)) -> dict:
    try:
        profile = await load_profile(user.bank_id)
        prefs = [p.model_dump() for p in profile.preferences]
    except HindsightError:
        prefs = None
    return {
        "user_id": user.id,
        "username": user.username,
        "hindsight": await hindsight.health(user.bank_id),
        "preferences": prefs,
    }
