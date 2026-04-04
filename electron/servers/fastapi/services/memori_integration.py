import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from importlib import import_module
from threading import Lock
from typing import Any, List, Optional

from models.llm_message import LLMMessage
from utils.db_utils import get_database_url_and_connect_args
from utils.get_env import (
    get_app_data_directory_env,
    get_memori_enabled_env,
    get_memori_entity_id_env,
    get_memori_process_id_env,
    get_memori_session_id_env,
    get_memori_sqlite_path_env,
)

LOGGER = logging.getLogger(__name__)

_DEFAULT_ENTITY_ID = "electron_user"
_DEFAULT_PROCESS_ID = "presenton"
_DEFAULT_SESSION_ID = "presenton-desktop"


@dataclass(frozen=True)
class MemoriScope:
    # Kept for backward compatibility with existing call sites.
    stage: str
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    allow_creative_influence: bool = False
    top_k: int = 3


def _env_memori_enabled() -> bool:
    """When unset, Memori is enabled with local sqlite storage."""
    raw = get_memori_enabled_env()
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


class MemoriIntegration:
    def __init__(self):
        self._memori_cls: Any | None = None
        self._memori_checked = False
        self._sqlite_db_path: Optional[str] = None
        self._storage_built = False
        self._storage_build_lock = Lock()
        self._singleton_lock = Lock()
        self._memori: Any | None = None

    def _sanitize(self, value: str, max_len: int = 100) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9:_\-.]", "_", value.strip())
        return cleaned[:max_len] if cleaned else "unknown"

    def _get_memori_cls(self) -> Any | None:
        if self._memori_checked:
            return self._memori_cls

        self._memori_checked = True
        try:
            self._memori_cls = getattr(import_module("memori"), "Memori", None)
        except Exception:
            self._memori_cls = None

        return self._memori_cls

    def _get_memori_sqlite_path(self) -> str:
        if self._sqlite_db_path:
            return self._sqlite_db_path

        env_path = get_memori_sqlite_path_env()
        if env_path and str(env_path).strip():
            db_path = os.path.normpath(str(env_path).strip())
        else:
            database_url, _ = get_database_url_and_connect_args()
            if database_url.startswith("sqlite+aiosqlite:///"):
                db_path = database_url[len("sqlite+aiosqlite:///") :]
            elif database_url.startswith("sqlite:///"):
                db_path = database_url[len("sqlite:///") :]
            else:
                app_data_dir = get_app_data_directory_env() or "/tmp/presenton"
                db_path = os.path.join(app_data_dir, "fastapi.db")

        parent_dir = os.path.dirname(db_path) or "."
        os.makedirs(parent_dir, exist_ok=True)

        self._sqlite_db_path = db_path
        return db_path

    def _get_memori_connection(self):
        # check_same_thread=False is required because Memori uses background workers.
        return sqlite3.connect(
            self._get_memori_sqlite_path(),
            timeout=30,
            check_same_thread=False,
        )

    def _build_storage_if_needed(self, mem: Any) -> None:
        if self._storage_built:
            return

        with self._storage_build_lock:
            if self._storage_built:
                return
            mem.config.storage.build()
            self._storage_built = True
            LOGGER.info(
                "memori.local_sqlite_ready path=%s",
                self._get_memori_sqlite_path(),
            )

    def _resolve_attribution(self) -> tuple[str, str]:
        entity_raw = get_memori_entity_id_env() or _DEFAULT_ENTITY_ID
        process_raw = get_memori_process_id_env() or _DEFAULT_PROCESS_ID
        return self._sanitize(str(entity_raw)), self._sanitize(str(process_raw))

    def _resolve_session_id(self) -> str:
        raw = get_memori_session_id_env()
        if raw and str(raw).strip():
            return self._sanitize(str(raw).strip(), max_len=120)
        return _DEFAULT_SESSION_ID

    def _create_memori_singleton(self) -> Any | None:
        """Create and configure a single Memori instance (local sqlite via conn factory)."""
        memori_cls = self._get_memori_cls()
        if memori_cls is None:
            LOGGER.warning("memori.unavailable package_not_found")
            return None

        mem = None
        try:
            # Memori expects a factory Callable[[], conn] or a connection; pass the
            # factory so background workers get their own connections.
            mem = memori_cls(conn=self._get_memori_connection)
            self._build_storage_if_needed(mem)

            entity_id, process_id = self._resolve_attribution()
            mem.attribution(entity_id=entity_id, process_id=process_id)
            session_id = self._resolve_session_id()
            mem.set_session(session_id)

            LOGGER.info(
                "memori.instance_ready sqlite_path=%s entity_id=%s process_id=%s session_id=%s",
                self._get_memori_sqlite_path(),
                entity_id,
                process_id,
                session_id,
            )

            return mem
        except Exception:
            LOGGER.exception("memori.local_init_failed")
            if mem is not None:
                try:
                    mem.close()
                except Exception:
                    pass
            return None

    def get_memori_singleton(self) -> Any | None:
        """Return the process-wide Memori instance, creating it once."""
        if not _env_memori_enabled():
            return None

        with self._singleton_lock:
            if self._memori is not None:
                return self._memori

            self._memori = self._create_memori_singleton()
            return self._memori

    def initialize_local_storage(self) -> bool:
        """Eagerly initialize Memori local sqlite storage at app startup."""
        if not _env_memori_enabled():
            LOGGER.info("memori.disabled_by_env")
            return False

        mem = self.get_memori_singleton()
        if mem is None:
            LOGGER.warning("memori.startup_init_failed")
            return False

        LOGGER.info(
            "memori.startup_init_success sqlite_path=%s",
            self._get_memori_sqlite_path(),
        )
        return True

    def shutdown(self) -> None:
        """Release Memori storage (e.g. on app shutdown)."""
        with self._singleton_lock:
            if self._memori is None:
                return
            try:
                self._memori.close()
            except Exception:
                LOGGER.exception("memori.shutdown_close_failed")
            self._memori = None
            self._storage_built = False
            self._sqlite_db_path = None

    def get_sqlite_path(self) -> str:
        return self._get_memori_sqlite_path()

    def apply_memory_guidance(
        self,
        messages: List[LLMMessage],
        scope: Optional[MemoriScope],
    ) -> List[LLMMessage]:
        # Intentionally a no-op: memory is handled directly by Memori's
        # client wrapper to capture full conversation turns.
        return messages

    def register_client(self, client: Any) -> Any:
        if not _env_memori_enabled():
            return client

        mem = self.get_memori_singleton()
        if mem is None:
            LOGGER.warning(
                "memori.register_skipped client_type=%s",
                type(client).__name__,
            )
            return client

        try:
            # Memori mutates the client methods in place and returns the Memori
            # instance (not the client). We must keep using the original client
            # object so provider-specific surfaces like `client.responses` remain
            # available (required by Codex / Responses API).
            mem.llm.register(client=client)

            # Keep Memori instance alive for the client lifecycle.
            setattr(client, "_presenton_memori", mem)
            LOGGER.info(
                "memori.register_success client_type=%s memori_installed=%s responses_wrapped=%s sqlite_path=%s",
                type(client).__name__,
                hasattr(client, "_memori_installed"),
                hasattr(client, "_responses_create"),
                self._get_memori_sqlite_path(),
            )
            return client
        except Exception:
            LOGGER.exception("memori.register_client_failed")
            return client


MEMORI_INTEGRATION = MemoriIntegration()
