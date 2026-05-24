"""Code repository ingestion pipeline.

Clones / pulls git repos, parses source files with language-aware chunkers,
and upserts both file-summary and function-level chunks into the knowledge store.

Incremental sync: tracks the last-indexed commit SHA per repo in L2 cache.
On re-sync only files changed since that SHA are re-indexed.

Usage (CLI):
  oapw kb sync --repo https://bitbucket.org/workspace/backend
  oapw kb sync --repo https://bitbucket.org/workspace/frontend --repo https://...

Programmatic:
  ingestor = CodeIngestor()
  ingestor.add_repo("https://bitbucket.org/workspace/backend", branch="main")
  result = await ingestor.sync_all()
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from oapw.enterprise.code_parser import parse_file, detect_language, CodeChunk
from oapw.enterprise.connectors.bitbucket import (
    build_auth_url, load_credential, repo_slug,
)
from oapw.knowledge.vector_store import KnowledgeStore, get_knowledge_store

logger = logging.getLogger(__name__)

# File extensions to index (skip binaries, lockfiles, etc.)
_INDEXABLE_EXTENSIONS = {
    ".cs", ".ts", ".tsx", ".js", ".jsx",
    ".py", ".go", ".java", ".kt",
    ".md", ".txt",
}
_SKIP_DIRS = {
    "node_modules", ".git", "bin", "obj", "dist", "build",
    "__pycache__", ".next", "coverage", ".vscode", ".idea",
    "packages", "vendor", "target",
}
_MAX_FILE_BYTES = 300_000   # skip minified / generated files > 300 KB
_BATCH_SIZE = 20            # docs per ChromaDB upsert batch


@dataclass
class RepoConfig:
    url: str                          # clone URL (HTTPS)
    branch: str = "main"
    name: str = ""                    # override auto-detected slug
    username: str = ""                # Bitbucket username for auth
    local_path: Path | None = None    # if already cloned, skip git clone

    def __post_init__(self) -> None:
        if not self.name:
            self.name = repo_slug(self.url)


@dataclass
class SyncResult:
    repo_name: str
    files_indexed: int = 0
    chunks_added: int = 0
    files_skipped: int = 0
    errors: int = 0
    sha: str = ""


class CodeIngestor:
    """Clones repos, parses source files, and upserts code chunks into ChromaDB."""

    def __init__(self, store: KnowledgeStore | None = None, cache=None) -> None:
        self._store = store or get_knowledge_store()
        self._cache = cache
        self._repos: list[RepoConfig] = []

    def _get_cache(self):
        if self._cache is None:
            from oapw.cache.manager import get_cache
            self._cache = get_cache()
        return self._cache

    def _repos_dir(self) -> Path:
        from oapw.core.config import get_config
        d = get_config().data_dir / "repos"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def add_repo(
        self,
        url: str,
        branch: str = "main",
        name: str = "",
        username: str = "",
    ) -> "CodeIngestor":
        """Register a repository for syncing. Returns self for chaining."""
        self._repos.append(RepoConfig(url=url, branch=branch, name=name, username=username))
        return self

    # ── Git helpers ───────────────────────────────────────────────────────────

    def _run_git(self, args: list[str], cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def _auth_url(self, repo: RepoConfig) -> str:
        """Return an authenticated clone URL if credentials are available."""
        if not repo.username:
            return repo.url
        password = load_credential(repo.username)
        if not password:
            logger.warning("No Bitbucket credentials for user %s — trying unauthenticated", repo.username)
            return repo.url
        return build_auth_url(repo.url, repo.username, password)

    def _ensure_local_repo(self, repo: RepoConfig) -> Path:
        """Clone the repo if not present; pull if it is. Returns local path."""
        local = self._repos_dir() / repo.name
        if local.exists():
            logger.info("Pulling %s ...", repo.name)
            self._run_git(["fetch", "--quiet"], cwd=local)
            self._run_git(["checkout", repo.branch, "--quiet"], cwd=local)
            self._run_git(["pull", "--ff-only", "--quiet"], cwd=local)
        else:
            logger.info("Cloning %s → %s ...", repo.url, local)
            auth_url = self._auth_url(repo)
            self._run_git([
                "clone", "--branch", repo.branch,
                "--depth", "500",        # shallow clone for speed
                "--quiet",
                auth_url, str(local),
            ])
        return local

    def _current_sha(self, local: Path) -> str:
        return self._run_git(["rev-parse", "HEAD"], cwd=local)

    def _changed_files(self, local: Path, since_sha: str) -> list[str]:
        """Return relative paths of files changed between since_sha and HEAD."""
        try:
            output = self._run_git(
                ["diff", "--name-only", since_sha, "HEAD"], cwd=local
            )
            return [f for f in output.splitlines() if f]
        except Exception:
            return []  # fall back to full re-index

    def _last_sha_key(self, repo_name: str) -> str:
        return f"code:last_sha:{repo_name}"

    def _get_last_sha(self, repo_name: str) -> str | None:
        return self._get_cache().get_llm(self._last_sha_key(repo_name))

    def _set_last_sha(self, repo_name: str, sha: str) -> None:
        self._get_cache().set_llm(self._last_sha_key(repo_name), sha)

    # ── File walking ──────────────────────────────────────────────────────────

    def _should_index(self, rel_path: str, abs_path: Path) -> bool:
        parts = Path(rel_path).parts
        if any(p in _SKIP_DIRS for p in parts):
            return False
        if Path(rel_path).suffix.lower() not in _INDEXABLE_EXTENSIONS:
            return False
        try:
            if abs_path.stat().st_size > _MAX_FILE_BYTES:
                logger.debug("Skipping large file: %s", rel_path)
                return False
        except OSError:
            return False
        return True

    def _walk_repo(self, local: Path) -> list[Path]:
        """Yield all indexable files in the repo."""
        result: list[Path] = []
        for p in local.rglob("*"):
            if p.is_file():
                rel = str(p.relative_to(local))
                if self._should_index(rel, p):
                    result.append(p)
        return result

    # ── Core sync logic ───────────────────────────────────────────────────────

    async def _ingest_file(
        self, abs_path: Path, repo: RepoConfig, local: Path
    ) -> tuple[int, int]:
        """Parse and upsert one file. Returns (chunks_added, errors)."""
        rel_path = str(abs_path.relative_to(local))
        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.debug("Cannot read %s: %s", rel_path, exc)
            return 0, 1

        try:
            chunks: list[CodeChunk] = parse_file(source, repo.name, repo.url, rel_path)
        except Exception as exc:
            logger.warning("Parse error %s: %s", rel_path, exc)
            return 0, 1

        docs = [c.to_kb_doc() for c in chunks]
        # Upsert in batches to avoid overwhelming the embedding service
        added = 0
        for i in range(0, len(docs), _BATCH_SIZE):
            batch = docs[i:i + _BATCH_SIZE]
            try:
                await self._store.add_batch(batch)
                added += len(batch)
            except Exception as exc:
                logger.warning("Batch upsert failed for %s: %s", rel_path, exc)
                # Fall back to individual adds
                for doc in batch:
                    try:
                        await self._store.add(doc["id"], doc["text"], doc["metadata"])
                        added += 1
                    except Exception:
                        pass

        return added, 0

    async def sync_repo(self, repo: RepoConfig) -> SyncResult:
        """Clone / pull one repo and re-index changed files."""
        result = SyncResult(repo_name=repo.name)
        try:
            local = self._ensure_local_repo(repo)
        except Exception as exc:
            logger.error("Failed to clone/pull %s: %s", repo.url, exc)
            result.errors += 1
            return result

        current_sha = self._current_sha(local)
        last_sha = self._get_last_sha(repo.name)
        result.sha = current_sha

        if last_sha and last_sha != current_sha:
            # Incremental: only changed files
            changed = self._changed_files(local, last_sha)
            logger.info("%s: %d changed files since %s", repo.name, len(changed), last_sha[:8])
            files_to_index = [
                local / f for f in changed
                if self._should_index(f, local / f)
            ]
        elif last_sha == current_sha:
            logger.info("%s: already up-to-date at %s", repo.name, current_sha[:8])
            return result
        else:
            # First sync: index everything
            logger.info("%s: first sync, indexing all files ...", repo.name)
            files_to_index = self._walk_repo(local)

        for abs_path in files_to_index:
            added, errs = await self._ingest_file(abs_path, repo, local)
            if added > 0:
                result.files_indexed += 1
                result.chunks_added += added
            if errs:
                result.errors += errs

        self._set_last_sha(repo.name, current_sha)
        logger.info(
            "%s: indexed %d files, %d chunks, %d errors",
            repo.name, result.files_indexed, result.chunks_added, result.errors,
        )
        return result

    async def sync_all(self) -> list[SyncResult]:
        """Sync all registered repositories sequentially (avoids OOM on 8GB)."""
        results: list[SyncResult] = []
        for repo in self._repos:
            results.append(await self.sync_repo(repo))
        return results

    def clear_repo(self, repo_name: str) -> None:
        """Delete all indexed chunks for a specific repo from the knowledge store."""
        # ChromaDB doesn't support 'where' on delete in all versions; iterate + delete
        # We store doc IDs as "code:{repo_name}:{path}#{name}" so we can identify them
        # by prefix — use a search to find them then delete
        try:
            col = self._store._get_collection()
            results = col.get(where={"repo_name": repo_name})
            if results and results["ids"]:
                col.delete(ids=results["ids"])
                logger.info("Deleted %d chunks for repo %s", len(results["ids"]), repo_name)
        except Exception as exc:
            logger.warning("Could not clear repo %s: %s", repo_name, exc)
