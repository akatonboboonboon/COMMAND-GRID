"""Database-backed accounts and long-lived login sessions for COMMAND GRID.

The rest of the application deliberately talks to :class:`AccountStore`
instead of using database-specific APIs.  Development uses SQLite by default;
setting ``DATABASE_URL`` to a PostgreSQL URL switches to psycopg without
changing callers.

Passwords and session tokens are never stored directly.  Passwords use
PBKDF2-HMAC-SHA256 with an individual random salt, while login sessions store
only a SHA-256 digest of a cryptographically random bearer token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import unicodedata
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote


PBKDF2_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 32
PASSWORD_HASH_BYTES = 32
SESSION_TOKEN_BYTES = 48
SESSION_LIFETIME = timedelta(days=30)
POSTGRES_CONNECT_TIMEOUT_SECONDS = 5

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
MIN_USERNAME_LENGTH = 2
MAX_USERNAME_LENGTH = 24
MIN_DISPLAY_NAME_LENGTH = 2
MAX_DISPLAY_NAME_LENGTH = 20

_USERNAME_PUNCTUATION = frozenset("._-")
_MAX_STORED_ITERATIONS = 5_000_000
_default_store: "AccountStore | None" = None
_default_store_lock = threading.Lock()


def _environment_flag(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in {"1", "true", "yes", "on"}


class AccountStoreError(Exception):
    """Base class for errors safe to translate into a user-facing message."""


class AccountConfigurationError(AccountStoreError):
    """The configured database backend cannot be used."""


class AccountValidationError(AccountStoreError, ValueError):
    """Registration or profile data does not satisfy the public contract."""


class DuplicateUsernameError(AccountStoreError):
    """A username is already registered (case-insensitively)."""


class AuthenticationError(AccountStoreError):
    """A username/password pair could not be authenticated."""


class AccountNotFoundError(AccountStoreError):
    """The requested account does not exist."""


class AccountDatabaseError(AccountStoreError):
    """A database operation failed without exposing implementation details."""


@dataclass(frozen=True, slots=True)
class Account:
    """Public, non-secret account information."""

    id: int
    username: str
    display_name: str
    created_at: str
    updated_at: str


class AccountStore:
    """Persist accounts, player state, and resumable login sessions.

    ``database_url`` may be a PostgreSQL URL, a ``sqlite:///`` URL, or a local
    filesystem path.  If omitted, ``DATABASE_URL`` is consulted and then
    ``ACCOUNT_DB_PATH``.  The final local fallback is
    ``command_grid_accounts.sqlite3`` beside this module.

    ``sqlite_path`` is a convenience for tests and local embedding.  It cannot
    be combined with ``database_url``.
    """

    def __init__(
        self,
        database_url: str | os.PathLike[str] | None = None,
        *,
        sqlite_path: str | os.PathLike[str] | None = None,
    ) -> None:
        if database_url is not None and sqlite_path is not None:
            raise AccountConfigurationError(
                "Choose either database_url or sqlite_path, not both."
            )

        self._lock = threading.RLock()
        self._memory_connection: sqlite3.Connection | None = None
        self._psycopg: Any | None = None

        source: str | os.PathLike[str] | None = database_url
        uses_environment_config = database_url is None and sqlite_path is None
        database_is_required = False
        if sqlite_path is not None:
            source = sqlite_path
        elif uses_environment_config:
            database_url_from_environment = os.getenv("DATABASE_URL")
            database_is_required = _environment_flag(
                "ACCOUNT_REQUIRE_DATABASE"
            ) or _environment_flag("RENDER")
            if database_is_required and not database_url_from_environment:
                raise AccountConfigurationError(
                    "DATABASE_URL is required for persistent account storage."
                )
            source = database_url_from_environment or os.getenv("ACCOUNT_DB_PATH")
        if source is None:
            source = Path(__file__).resolve().with_name(
                "command_grid_accounts.sqlite3"
            )

        source_text = os.fspath(source)
        if (
            uses_environment_config
            and database_is_required
            and not source_text.startswith(("postgresql://", "postgres://"))
        ):
            raise AccountConfigurationError(
                "DATABASE_URL must be a PostgreSQL URL on Render."
            )
        if source_text.startswith(("postgresql://", "postgres://")):
            self.backend = "postgresql"
            if source_text.startswith("postgres://"):
                source_text = "postgresql://" + source_text[len("postgres://") :]
            self._database_url = source_text
            self._sqlite_path: str | None = None
            try:
                import psycopg  # type: ignore[import-not-found]
            except (ImportError, ModuleNotFoundError):
                raise AccountConfigurationError(
                    "PostgreSQL support is unavailable."
                ) from None
            self._psycopg = psycopg
        else:
            self.backend = "sqlite"
            self._database_url = None
            self._sqlite_path = self._sqlite_path_from_source(source_text)
            if self._sqlite_path != ":memory:":
                self._sqlite_path = os.fspath(Path(self._sqlite_path).expanduser())

        self._initialize_schema()

    @staticmethod
    def _sqlite_path_from_source(source: str) -> str:
        if "://" in source and not source.startswith("sqlite:///"):
            raise AccountConfigurationError("Unsupported account database URL.")
        if source.startswith("sqlite:///"):
            source = unquote(source[len("sqlite:///") :])
        if not source:
            raise AccountConfigurationError("SQLite database path is empty.")
        return source

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        if self.backend == "postgresql":
            try:
                assert self._psycopg is not None
                assert self._database_url is not None
                with self._psycopg.connect(
                    self._database_url,
                    connect_timeout=POSTGRES_CONNECT_TIMEOUT_SECONDS,
                ) as connection:
                    yield connection
            except AccountStoreError:
                raise
            return

        assert self._sqlite_path is not None
        with self._lock:
            shared = self._sqlite_path == ":memory:"
            connection: sqlite3.Connection | None = None
            try:
                if shared:
                    if self._memory_connection is None:
                        self._memory_connection = sqlite3.connect(
                            ":memory:", timeout=5.0, check_same_thread=False
                        )
                        self._memory_connection.row_factory = sqlite3.Row
                    connection = self._memory_connection
                else:
                    connection = sqlite3.connect(self._sqlite_path, timeout=5.0)
                    connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA busy_timeout = 5000")
                yield connection
            except Exception:
                if connection is not None:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                raise
            finally:
                if connection is not None and not shared:
                    connection.close()

    def _initialize_schema(self) -> None:
        if self.backend == "sqlite":
            assert self._sqlite_path is not None
            if self._sqlite_path != ":memory:":
                try:
                    Path(self._sqlite_path).expanduser().resolve().parent.mkdir(
                        parents=True, exist_ok=True
                    )
                except (OSError, RuntimeError):
                    raise AccountDatabaseError(
                        "The account database could not be prepared."
                    ) from None
            account_id = "INTEGER PRIMARY KEY AUTOINCREMENT"
            binary_type = "BLOB"
        else:
            account_id = "BIGSERIAL PRIMARY KEY"
            binary_type = "BYTEA"

        account_schema = f"""
            CREATE TABLE IF NOT EXISTS accounts (
                id {account_id},
                username VARCHAR(24) NOT NULL UNIQUE,
                display_name VARCHAR(20) NOT NULL,
                password_salt {binary_type} NOT NULL,
                password_hash {binary_type} NOT NULL,
                password_iterations INTEGER NOT NULL,
                player_state TEXT NOT NULL,
                created_at VARCHAR(40) NOT NULL,
                updated_at VARCHAR(40) NOT NULL
            )
        """
        session_schema = f"""
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash {binary_type} PRIMARY KEY,
                account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                created_at VARCHAR(40) NOT NULL,
                expires_at VARCHAR(40) NOT NULL
            )
        """
        index_schema = """
            CREATE INDEX IF NOT EXISTS sessions_expires_at_idx
            ON sessions (expires_at)
        """
        try:
            with self._connection() as connection:
                connection.execute(account_schema)
                connection.execute(session_schema)
                connection.execute(index_schema)
                connection.commit()
        except Exception:
            raise AccountDatabaseError(
                "The account database could not be initialized."
            ) from None

    @staticmethod
    def _placeholder(backend: str) -> str:
        return "?" if backend == "sqlite" else "%s"

    @property
    def _p(self) -> str:
        return self._placeholder(self.backend)

    @staticmethod
    def _normalize_username(username: str) -> str:
        if not isinstance(username, str):
            raise AccountValidationError("ユーザー名を文字で入力してください。")
        cleaned = unicodedata.normalize("NFKC", username.strip())
        canonical = unicodedata.normalize("NFKC", cleaned.casefold())
        if (
            not MIN_USERNAME_LENGTH <= len(cleaned) <= MAX_USERNAME_LENGTH
            or len(canonical) > MAX_USERNAME_LENGTH
        ):
            raise AccountValidationError(
                "ユーザー名は2〜24文字で入力してください。日本語も使用できます。"
            )
        if not all(
            character.isalnum() or character in _USERNAME_PUNCTUATION
            for character in canonical
        ) or not any(character.isalnum() for character in canonical):
            raise AccountValidationError(
                "ユーザー名には日本語・英数字と . _ - だけを使用できます。"
            )
        return canonical

    @staticmethod
    def _normalize_display_name(display_name: str) -> str:
        if not isinstance(display_name, str):
            raise AccountValidationError("表示名を文字で入力してください。")
        cleaned = " ".join(display_name.split())
        if not MIN_DISPLAY_NAME_LENGTH <= len(cleaned) <= MAX_DISPLAY_NAME_LENGTH:
            raise AccountValidationError("表示名は2〜20文字で入力してください。")
        if not cleaned.isprintable() or "\x00" in cleaned:
            raise AccountValidationError("表示名に使用できない文字が含まれています。")
        return cleaned

    @staticmethod
    def _validate_password(password: str) -> str:
        if not isinstance(password, str):
            raise AccountValidationError("パスワードを文字で入力してください。")
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            raise AccountValidationError("パスワードは8〜256文字で入力してください。")
        try:
            password.encode("utf-8")
        except UnicodeEncodeError:
            raise AccountValidationError(
                "パスワードに使用できない文字が含まれています。"
            ) from None
        return password

    @staticmethod
    def _encode_player_state(player_state: Mapping[str, Any]) -> str:
        if not isinstance(player_state, Mapping):
            raise AccountValidationError("Player state must be a JSON object.")
        try:
            encoded = json.dumps(
                dict(player_state),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            encoded.encode("utf-8")
            decoded = json.loads(encoded)
        except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
            raise AccountValidationError("Player state must be valid JSON.") from None
        if not isinstance(decoded, dict):
            raise AccountValidationError("Player state must be a JSON object.")
        return encoded

    @staticmethod
    def _decode_player_state(value: Any) -> dict[str, Any]:
        try:
            decoded = value if isinstance(value, dict) else json.loads(str(value))
            if not isinstance(decoded, dict):
                raise ValueError
            # A JSON round trip detaches data returned by database adapters.
            return json.loads(
                json.dumps(decoded, ensure_ascii=False, allow_nan=False)
            )
        except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
            raise AccountDatabaseError("Stored player state is invalid.") from None

    @staticmethod
    def _password_hash(password: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
            dklen=PASSWORD_HASH_BYTES,
        )

    @staticmethod
    def _row_value(row: Any, name: str, index: int) -> Any:
        try:
            return row[name]
        except (KeyError, TypeError, IndexError):
            return row[index]

    @classmethod
    def _account_from_row(cls, row: Any) -> Account:
        return Account(
            id=int(cls._row_value(row, "id", 0)),
            username=str(cls._row_value(row, "username", 1)),
            display_name=str(cls._row_value(row, "display_name", 2)),
            created_at=str(cls._row_value(row, "created_at", 3)),
            updated_at=str(cls._row_value(row, "updated_at", 4)),
        )

    @staticmethod
    def _utc_now(now: datetime | None = None) -> datetime:
        if now is None:
            return datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise AccountValidationError("Session time must include a timezone.")
        return now.astimezone(timezone.utc)

    @staticmethod
    def _time_text(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")

    def register(
        self,
        username: str,
        password: str,
        display_name: str | None = None,
        player_state: Mapping[str, Any] | None = None,
    ) -> Account:
        """Register and return an account, rejecting case-insensitive duplicates."""

        normalized_username = self._normalize_username(username)
        cleaned_display_name = self._normalize_display_name(
            unicodedata.normalize("NFKC", username.strip())[
                :MAX_DISPLAY_NAME_LENGTH
            ]
            if display_name is None
            else display_name
        )
        clean_password = self._validate_password(password)
        encoded_state = self._encode_player_state(
            {} if player_state is None else player_state
        )
        salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
        password_digest = self._password_hash(
            clean_password, salt, PBKDF2_ITERATIONS
        )
        timestamp = self._time_text(self._utc_now())
        p = self._p

        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    f"""
                        INSERT INTO accounts (
                            username, display_name, password_salt, password_hash,
                            password_iterations, player_state, created_at, updated_at
                        ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                    """,
                    (
                        normalized_username,
                        cleaned_display_name,
                        salt,
                        password_digest,
                        PBKDF2_ITERATIONS,
                        encoded_state,
                        timestamp,
                        timestamp,
                    ),
                )
                account_id = cursor.lastrowid if self.backend == "sqlite" else None
                if account_id is None:
                    row = connection.execute(
                        f"SELECT id FROM accounts WHERE username = {p}",
                        (normalized_username,),
                    ).fetchone()
                    account_id = self._row_value(row, "id", 0)
                connection.commit()
        except Exception as exc:
            if isinstance(exc, sqlite3.IntegrityError) or (
                self._psycopg is not None
                and isinstance(exc, self._psycopg.errors.UniqueViolation)
            ):
                raise DuplicateUsernameError("Username is already registered.") from None
            raise AccountDatabaseError("Account registration failed.") from None

        return Account(
            id=int(account_id),
            username=normalized_username,
            display_name=cleaned_display_name,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def authenticate(self, username: str, password: str) -> Account:
        """Authenticate credentials using a constant-time digest comparison."""

        try:
            normalized_username = self._normalize_username(username)
            username_valid = True
        except AccountValidationError:
            normalized_username = "_invalid_"
            username_valid = False

        password_valid = isinstance(password, str) and len(password) <= MAX_PASSWORD_LENGTH
        if password_valid:
            try:
                password.encode("utf-8")
            except UnicodeEncodeError:
                password_valid = False
        candidate_password = password if password_valid else ""
        p = self._p
        try:
            with self._connection() as connection:
                row = connection.execute(
                    f"""
                        SELECT id, username, display_name, created_at, updated_at,
                               password_salt, password_hash, password_iterations
                        FROM accounts WHERE username = {p}
                    """,
                    (normalized_username,),
                ).fetchone()
        except Exception:
            raise AccountDatabaseError("Account authentication failed.") from None

        if row is None:
            salt = b"\0" * PASSWORD_SALT_BYTES
            expected = b"\0" * PASSWORD_HASH_BYTES
            iterations = PBKDF2_ITERATIONS
        else:
            try:
                salt = bytes(self._row_value(row, "password_salt", 5))
                expected = bytes(self._row_value(row, "password_hash", 6))
                iterations = int(self._row_value(row, "password_iterations", 7))
                if not 1 <= iterations <= _MAX_STORED_ITERATIONS:
                    raise ValueError
            except (TypeError, ValueError):
                raise AccountDatabaseError("Stored account credentials are invalid.") from None

        candidate = self._password_hash(candidate_password, salt, iterations)
        matches = hmac.compare_digest(candidate, expected)
        if row is None or not username_valid or not password_valid or not matches:
            raise AuthenticationError("Invalid username or password.")
        try:
            return self._account_from_row(row)
        except (TypeError, ValueError, KeyError, IndexError):
            raise AccountDatabaseError("Stored account information is invalid.") from None

    def load_player_state(self, username: str) -> dict[str, Any]:
        """Load the JSON player state for ``username``."""

        normalized_username = self._normalize_username(username)
        p = self._p
        try:
            with self._connection() as connection:
                row = connection.execute(
                    f"SELECT player_state FROM accounts WHERE username = {p}",
                    (normalized_username,),
                ).fetchone()
        except Exception:
            raise AccountDatabaseError("Player state could not be loaded.") from None
        if row is None:
            raise AccountNotFoundError("Account was not found.")
        return self._decode_player_state(self._row_value(row, "player_state", 0))

    def save_player_state(
        self, username: str, player_state: Mapping[str, Any]
    ) -> None:
        """Atomically replace an account's JSON player state."""

        normalized_username = self._normalize_username(username)
        encoded_state = self._encode_player_state(player_state)
        timestamp = self._time_text(self._utc_now())
        p = self._p
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    f"""
                        UPDATE accounts SET player_state = {p}, updated_at = {p}
                        WHERE username = {p}
                    """,
                    (encoded_state, timestamp, normalized_username),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise AccountNotFoundError("Account was not found.")
                connection.commit()
        except AccountNotFoundError:
            raise
        except Exception:
            raise AccountDatabaseError("Player state could not be saved.") from None

    def update_display_name(self, username: str, display_name: str) -> Account:
        """Change an account's public display name and return fresh metadata."""

        normalized_username = self._normalize_username(username)
        cleaned_display_name = self._normalize_display_name(display_name)
        timestamp = self._time_text(self._utc_now())
        p = self._p
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    f"""
                        UPDATE accounts SET display_name = {p}, updated_at = {p}
                        WHERE username = {p}
                    """,
                    (cleaned_display_name, timestamp, normalized_username),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise AccountNotFoundError("Account was not found.")
                row = connection.execute(
                    f"""
                        SELECT id, username, display_name, created_at, updated_at
                        FROM accounts WHERE username = {p}
                    """,
                    (normalized_username,),
                ).fetchone()
                connection.commit()
        except AccountNotFoundError:
            raise
        except Exception:
            raise AccountDatabaseError("Display name could not be updated.") from None
        try:
            return self._account_from_row(row)
        except (TypeError, ValueError, KeyError, IndexError):
            raise AccountDatabaseError("Stored account information is invalid.") from None

    @staticmethod
    def _session_digest(token: str) -> bytes | None:
        if not isinstance(token, str) or not 20 <= len(token) <= 512:
            return None
        try:
            return hashlib.sha256(token.encode("utf-8")).digest()
        except UnicodeEncodeError:
            return None

    def create_session(self, username: str, *, now: datetime | None = None) -> str:
        """Create a 30-day login session and return its one-time raw token."""

        normalized_username = self._normalize_username(username)
        issued_at = self._utc_now(now)
        expires_at = issued_at + SESSION_LIFETIME
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        token_hash = self._session_digest(token)
        assert token_hash is not None
        p = self._p
        try:
            with self._connection() as connection:
                account_row = connection.execute(
                    f"SELECT id FROM accounts WHERE username = {p}",
                    (normalized_username,),
                ).fetchone()
                if account_row is None:
                    raise AccountNotFoundError("Account was not found.")
                account_id = int(self._row_value(account_row, "id", 0))
                connection.execute(
                    f"""
                        INSERT INTO sessions
                            (token_hash, account_id, created_at, expires_at)
                        VALUES ({p}, {p}, {p}, {p})
                    """,
                    (
                        token_hash,
                        account_id,
                        self._time_text(issued_at),
                        self._time_text(expires_at),
                    ),
                )
                connection.commit()
        except AccountNotFoundError:
            raise
        except Exception:
            raise AccountDatabaseError("Login session could not be created.") from None
        return token

    def resolve_session(
        self, token: str, *, now: datetime | None = None
    ) -> Account | None:
        """Return the account for a live token, deleting it if it has expired."""

        token_hash = self._session_digest(token)
        if token_hash is None:
            return None
        current_time = self._utc_now(now)
        p = self._p
        try:
            with self._connection() as connection:
                row = connection.execute(
                    f"""
                        SELECT a.id, a.username, a.display_name,
                               a.created_at, a.updated_at, s.expires_at
                        FROM sessions AS s
                        JOIN accounts AS a ON a.id = s.account_id
                        WHERE s.token_hash = {p}
                    """,
                    (token_hash,),
                ).fetchone()
                if row is None:
                    return None
                expires_text = str(self._row_value(row, "expires_at", 5))
                try:
                    expires_at = datetime.fromisoformat(expires_text)
                    if expires_at.tzinfo is None:
                        raise ValueError
                    expires_at = expires_at.astimezone(timezone.utc)
                except ValueError:
                    raise AccountDatabaseError("Stored login session is invalid.")
                if expires_at <= current_time:
                    connection.execute(
                        f"DELETE FROM sessions WHERE token_hash = {p}",
                        (token_hash,),
                    )
                    connection.commit()
                    return None
                return self._account_from_row(row)
        except AccountDatabaseError:
            raise
        except Exception:
            raise AccountDatabaseError("Login session could not be resolved.") from None

    def delete_session(self, token: str) -> bool:
        """Invalidate one login token.  Invalid or unknown tokens are harmless."""

        token_hash = self._session_digest(token)
        if token_hash is None:
            return False
        p = self._p
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    f"DELETE FROM sessions WHERE token_hash = {p}",
                    (token_hash,),
                )
                connection.commit()
                return cursor.rowcount == 1
        except Exception:
            raise AccountDatabaseError("Login session could not be deleted.") from None

    def purge_expired_sessions(self, *, now: datetime | None = None) -> int:
        """Delete all expired sessions and return the number removed."""

        cutoff = self._time_text(self._utc_now(now))
        p = self._p
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    f"DELETE FROM sessions WHERE expires_at <= {p}", (cutoff,)
                )
                connection.commit()
                return max(0, int(cursor.rowcount))
        except Exception:
            raise AccountDatabaseError("Expired sessions could not be purged.") from None

    def close(self) -> None:
        """Release the retained SQLite in-memory connection, if any."""

        with self._lock:
            if self._memory_connection is not None:
                self._memory_connection.close()
            self._memory_connection = None

    def __enter__(self) -> "AccountStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def get_default_account_store() -> AccountStore:
    """Return the process-wide store configured by environment variables."""

    global _default_store
    if _default_store is None:
        with _default_store_lock:
            if _default_store is None:
                _default_store = AccountStore()
    return _default_store


__all__ = [
    "Account",
    "AccountConfigurationError",
    "AccountDatabaseError",
    "AccountNotFoundError",
    "AccountStore",
    "AccountStoreError",
    "AccountValidationError",
    "AuthenticationError",
    "DuplicateUsernameError",
    "get_default_account_store",
    "PBKDF2_ITERATIONS",
    "SESSION_LIFETIME",
]
