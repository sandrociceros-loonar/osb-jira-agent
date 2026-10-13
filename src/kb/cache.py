"""Knowledge Base Cache manager with disk persistence and thread-safe updating state."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from src.kb.models import KBChunk, KBPage
from src.utils.logger import setup_logger

logger = setup_logger("kb-cache")


class KBCacheManager:
    """Gerenciador de cache local com persistência em disco e controle de estado de atualização."""

    def __init__(
        self,
        cache_dir: str | Path = ".cache/kb",
        space_key: str = "osbjiraage",
        ttl_seconds: int = 3600,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.space_key = space_key.strip()
        self.ttl_seconds = ttl_seconds
        self.cache_file = self.cache_dir / f"confluence_{self.space_key}_cache.json"

        self._lock = threading.Lock()
        self._is_updating = False
        self._cached_pages: list[KBPage] = []
        self._cached_chunks: list[KBChunk] = []
        self._last_loaded_at: datetime | None = None

    def is_updating(self) -> bool:
        """Indica se o cache está em processo de sincronização/atualização."""
        with self._lock:
            return self._is_updating

    def set_updating(self, status: bool) -> None:
        """Altera o status de atualização do cache de forma thread-safe."""
        with self._lock:
            self._is_updating = status
            logger.info("KB Cache para espaço '%s' - is_updating=%s", self.space_key, status)

    def is_valid(self) -> bool:
        """Verifica se os dados em memória ou em disco ainda estão válidos pelo TTL."""
        if not self._cached_chunks:
            return False
        if not self._last_loaded_at:
            return False
        age = (datetime.now(UTC) - self._last_loaded_at).total_seconds()
        return age <= self.ttl_seconds

    def get_chunks(self) -> list[KBChunk]:
        """Retorna os chunks em memória, tentando carregar do disco caso necessário."""
        with self._lock:
            if self._cached_chunks and self.is_valid():
                return list(self._cached_chunks)

        loaded = self.load_from_disk()
        if loaded:
            return loaded

        return list(self._cached_chunks)

    def get_pages(self) -> list[KBPage]:
        """Retorna as páginas em memória."""
        with self._lock:
            return list(self._cached_pages)

    def save_cache(self, pages: list[KBPage], chunks: list[KBChunk]) -> None:
        """Salva páginas e chunks em memória e persiste em arquivo JSON."""
        now = datetime.now(UTC)
        with self._lock:
            self._cached_pages = list(pages)
            self._cached_chunks = list(chunks)
            self._last_loaded_at = now

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "space_key": self.space_key,
                "saved_at": now.isoformat(),
                "pages_count": len(pages),
                "chunks_count": len(chunks),
                "pages": [p.model_dump(mode="json") for p in pages],
                "chunks": [c.model_dump(mode="json") for c in chunks],
            }
            temp_file = self.cache_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_file.replace(self.cache_file)
            logger.info(
                "KB Cache salvo com sucesso: %d páginas, %d chunks em %s",
                len(pages),
                len(chunks),
                self.cache_file,
            )
        except Exception as exc:
            logger.error("Falha ao salvar KB Cache no disco: %s", exc)

    def load_from_disk(self) -> list[KBChunk] | None:
        """Tenta carregar o cache a partir do disco respeitando o TTL."""
        if not self.cache_file.exists():
            return None

        try:
            content = self.cache_file.read_text(encoding="utf-8")
            data = json.loads(content)

            saved_at_raw = data.get("saved_at")
            if saved_at_raw:
                saved_at = datetime.fromisoformat(saved_at_raw)
                age = (datetime.now(UTC) - saved_at).total_seconds()
                if age > self.ttl_seconds:
                    logger.info("KB Cache em disco expirou (idade: %.0fs, ttl: %ds).", age, self.ttl_seconds)
                    return None

            pages_raw = data.get("pages", [])
            chunks_raw = data.get("chunks", [])

            pages = [KBPage.model_validate(p) for p in pages_raw]
            chunks = [KBChunk.model_validate(c) for c in chunks_raw]

            with self._lock:
                self._cached_pages = pages
                self._cached_chunks = chunks
                self._last_loaded_at = datetime.now(UTC)

            logger.info(
                "KB Cache carregado do disco: %d páginas, %d chunks.",
                len(pages),
                len(chunks),
            )
            return chunks

        except Exception as exc:
            logger.warning("Falha ao ler KB Cache do disco (%s): %s", self.cache_file, exc)
            return None

    def invalidate(self) -> None:
        """Limpa o cache em memória e remove o arquivo de disco."""
        with self._lock:
            self._cached_pages.clear()
            self._cached_chunks.clear()
            self._last_loaded_at = None

        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
                logger.info("Arquivo de cache %s removido.", self.cache_file)
        except Exception as exc:
            logger.warning("Erro ao excluir arquivo de cache: %s", exc)
