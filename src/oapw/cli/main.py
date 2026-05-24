"""oapw CLI — entry point for all framework commands."""

from __future__ import annotations

import asyncio
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from oapw import __version__

app = typer.Typer(
    name="oapw",
    help="Ollama + Playwright AI Automation Framework",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()

# ── Sub-app groups ────────────────────────────────────────────────────────────
cache_app = typer.Typer(name="cache", help="Cache management commands", no_args_is_help=True)
kb_app = typer.Typer(name="kb", help="Knowledge base commands (Jira + Confluence)", no_args_is_help=True)
auth_app = typer.Typer(name="auth", help="Credential management", no_args_is_help=True)
generate_app = typer.Typer(name="generate", help="Test generation commands", no_args_is_help=True)
app.add_typer(cache_app)
app.add_typer(kb_app)
app.add_typer(auth_app)
app.add_typer(generate_app)


# ── doctor ────────────────────────────────────────────────────────────────────

@app.command()
def doctor() -> None:
    """Verify that all runtime dependencies are installed and reachable."""
    asyncio.run(_doctor())


async def _doctor() -> None:
    from oapw.core.config import get_config
    from oapw.core.ollama_client import get_ollama_client

    cfg = get_config()
    checks: list[tuple[str, bool, str]] = []

    # Python version
    py_ok = sys.version_info >= (3, 11)
    checks.append(("Python ≥ 3.11", py_ok, platform.python_version()))

    # Ollama reachable
    client = get_ollama_client()
    ollama_ok = await client.is_running()
    checks.append(("Ollama server", ollama_ok, cfg.ollama_base_url))

    # Required models
    if ollama_ok:
        models = await client.list_models()
        for model in [cfg.ollama_default_model, cfg.ollama_embed_model]:
            present = any(m.startswith(model.split(":")[0]) for m in models)
            checks.append((f"Model: {model}", present, "pulled" if present else "run: ollama pull " + model))
    else:
        checks.append((f"Model: {cfg.ollama_default_model}", False, "Ollama not running"))
        checks.append((f"Model: {cfg.ollama_embed_model}", False, "Ollama not running"))

    # Playwright browsers
    pw_ok = _check_playwright()
    checks.append(("Playwright chromium", pw_ok, "installed" if pw_ok else "run: playwright install chromium"))

    # RAM estimate
    ram_gb = _get_ram_gb()
    ram_ok = ram_gb >= 8
    checks.append(("RAM ≥ 8 GB", ram_ok, f"{ram_gb} GB detected"))

    # Cache dir writable
    try:
        cfg.ensure_dirs()
        dir_ok = True
        dir_msg = str(cfg.data_dir)
    except Exception as e:
        dir_ok = False
        dir_msg = str(e)
    checks.append(("Cache dir writable", dir_ok, dir_msg))

    _render_checks(checks)

    all_pass = all(ok for _, ok, _ in checks)
    if all_pass:
        console.print(Panel(f"[bold green]✓ All checks passed — oapw v{__version__} ready![/]", box=box.ROUNDED))
    else:
        failed = sum(1 for _, ok, _ in checks if not ok)
        console.print(Panel(f"[bold yellow]{failed} check(s) need attention — see table above.[/]", box=box.ROUNDED))
        raise typer.Exit(1)


def _render_checks(checks: list[tuple[str, bool, str]]) -> None:
    table = Table(title="oapw doctor", box=box.ROUNDED, show_header=True)
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Detail")
    for name, ok, detail in checks:
        status = "[green]✓[/]" if ok else "[red]✗[/]"
        table.add_row(name, status, detail)
    console.print(table)


def _check_playwright() -> bool:
    try:
        result = subprocess.run(
            ["python", "-c", "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.stop()"],
            capture_output=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _get_ram_gb() -> int:
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
            )
            return int(result.stdout.strip()) // (1024 ** 3)
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    kb = int(line.split()[1])
                    return kb // (1024 ** 2)
    except Exception:
        pass
    return 0


# ── cache sub-commands ────────────────────────────────────────────────────────

@cache_app.command("stats")
def cache_stats() -> None:
    """Show cache hit rates and sizes."""
    from oapw.cache.manager import get_cache
    stats = get_cache().stats()
    _print_cache_stats(stats)


@cache_app.command("clear")
def cache_clear(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Wipe all cached data (L1 + L2)."""
    if not confirm:
        typer.confirm("This will delete all cached LLM responses, locators, and plans. Continue?", abort=True)
    from oapw.cache.manager import get_cache
    get_cache().clear_all()
    console.print("[green]Cache cleared.[/]")


@cache_app.command("prune")
def cache_prune() -> None:
    """Remove expired entries from the SQLite cache."""
    from oapw.cache.manager import get_cache
    removed = get_cache().prune()
    console.print(f"[green]Pruned {removed} expired entries.[/]")


def _print_cache_stats(stats: dict) -> None:
    table = Table(title="Cache Statistics", box=box.ROUNDED)
    table.add_column("Layer")
    table.add_column("Hits", justify="right")
    table.add_column("Misses", justify="right")
    table.add_column("Size", justify="right")

    l1 = stats["l1"]
    table.add_row("L1 Memory (LRU)", str(l1["hits"]), str(l1["misses"]),
                  f"{l1['size']} / {l1['max_size']}")

    l2 = stats["l2"]
    table.add_row("L2 Disk (SQLite)", str(l2["hits"]), str(l2["misses"]),
                  f"{l2['rows']} rows")
    console.print(table)


# ── kb sub-commands ───────────────────────────────────────────────────────────

@kb_app.command("sync")
def kb_sync(
    jira: Optional[str] = typer.Option(None, "--jira", help="JQL query, e.g. 'project = PROJ AND issuetype = Story'"),
    confluence: Optional[str] = typer.Option(None, "--confluence", help="CQL query, e.g. 'label = qa AND space = ENG'"),
    repo: Optional[list[str]] = typer.Option(None, "--repo", help="Git repo URL (repeatable). e.g. --repo https://bitbucket.org/ws/backend --repo https://bitbucket.org/ws/frontend"),
    component: Optional[str] = typer.Option(None, "--component", help="Jira component name for Confluence weighting"),
    branch: str = typer.Option("main", "--branch", help="Git branch for --repo syncs"),
    username: Optional[str] = typer.Option(None, "--username", help="Bitbucket username (uses keyring credential)"),
    max_results: int = typer.Option(50, "--max", help="Max items per Jira/Confluence source"),
) -> None:
    """Sync Jira tickets, Confluence pages, and/or code repos into the knowledge base."""
    asyncio.run(_kb_sync(jira, confluence, repo or [], component, branch, username, max_results))


async def _kb_sync(
    jira_jql: str | None,
    conf_cql: str | None,
    repos: list[str],
    component: str | None,
    branch: str,
    username: str | None,
    max_results: int,
) -> None:
    if not jira_jql and not conf_cql and not repos:
        console.print("[yellow]Provide at least --jira, --confluence, or --repo.[/]")
        raise typer.Exit(1)

    if jira_jql:
        try:
            from oapw.enterprise.jira_ingest import JiraIngestor
            console.print(f"[bold]Ingesting Jira:[/] {jira_jql}")
            result = await JiraIngestor().ingest_query(jira_jql, max_results=max_results)
            console.print(
                f"  [green]✓[/] {result.added}/{result.total} tickets ingested"
                + (f" ({result.errors} errors)" if result.errors else "")
            )
        except Exception as exc:
            console.print(f"[red]Jira ingest failed:[/] {exc}")

    if conf_cql:
        try:
            from oapw.enterprise.confluence_ingest import ConfluenceIngestor
            console.print(f"[bold]Ingesting Confluence:[/] {conf_cql}")
            result = await ConfluenceIngestor().ingest_query(
                conf_cql, max_results=max_results, component=component
            )
            console.print(
                f"  [green]✓[/] {result.added}/{result.total} pages ingested"
                + (f" ({result.errors} errors)" if result.errors else "")
            )
        except Exception as exc:
            console.print(f"[red]Confluence ingest failed:[/] {exc}")

    if repos:
        try:
            from oapw.enterprise.code_ingest import CodeIngestor
            ingestor = CodeIngestor()
            for url in repos:
                ingestor.add_repo(url, branch=branch, username=username or "")
            console.print(f"[bold]Syncing {len(repos)} code repo(s):[/]")
            results = await ingestor.sync_all()
            for r in results:
                if r.errors and not r.files_indexed:
                    console.print(f"  [red]✗[/] {r.repo_name}: failed ({r.errors} errors)")
                else:
                    status = "[green]✓[/]" if not r.errors else "[yellow]⚠[/]"
                    console.print(
                        f"  {status} {r.repo_name}: "
                        f"{r.files_indexed} files, {r.chunks_added} chunks"
                        + (f", sha {r.sha[:8]}" if r.sha else "")
                        + (f" ({r.errors} errors)" if r.errors else "")
                    )
        except Exception as exc:
            console.print(f"[red]Code ingest failed:[/] {exc}")


@kb_app.command("stats")
def kb_stats() -> None:
    """Show knowledge base document counts."""
    try:
        from oapw.knowledge.vector_store import get_knowledge_store
        store = get_knowledge_store()
        n = store.count()
        console.print(f"Knowledge base: [bold]{n}[/] documents indexed")
    except RuntimeError as exc:
        console.print(f"[yellow]{exc}[/]")


@kb_app.command("clear")
def kb_clear(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Remove all documents from the knowledge base."""
    if not confirm:
        typer.confirm("This will delete all indexed Jira/Confluence documents. Continue?", abort=True)
    try:
        from oapw.knowledge.vector_store import get_knowledge_store
        get_knowledge_store().clear()
        console.print("[green]Knowledge base cleared.[/]")
    except RuntimeError as exc:
        console.print(f"[yellow]{exc}[/]")


@kb_app.command("coverage")
def kb_coverage() -> None:
    """Show which Jira tickets have traced automated tests."""
    from oapw.core.config import get_config
    from oapw.enterprise.traceability import TraceabilityStore
    store = TraceabilityStore(db_path=get_config().traceability_db)
    summary = store.coverage_summary()
    table = Table(title="Test Coverage Summary", box=box.ROUNDED)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Tests with traceability", str(summary["total_tests_traced"]))
    table.add_row("Jira tickets covered", str(summary["jira_tickets_covered"]))
    if summary["jira_keys"]:
        table.add_row("Ticket keys", ", ".join(summary["jira_keys"][:10]))
    console.print(table)


# ── auth sub-commands ─────────────────────────────────────────────────────────

@auth_app.command("bitbucket")
def auth_bitbucket(
    username: str = typer.Option(..., "--username", "-u", help="Bitbucket username"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="App Password (prompted if omitted)"),
) -> None:
    """Store your Bitbucket App Password in the OS keyring."""
    if not password:
        password = typer.prompt("Bitbucket App Password", hide_input=True)
    from oapw.enterprise.connectors.bitbucket import save_credential
    save_credential(username, password)
    console.print(f"[green]✓[/] Credential saved for {username}. Use --username {username} with oapw kb sync --repo.")


@auth_app.command("atlassian")
def auth_atlassian(
    email: str = typer.Option(..., "--email", "-e", help="Atlassian account email"),
    token: Optional[str] = typer.Option(None, "--token", "-t", help="API token (prompted if omitted)"),
) -> None:
    """Store your Atlassian API token in the OS keyring."""
    if not token:
        token = typer.prompt("Atlassian API token", hide_input=True)
    from oapw.enterprise.atlassian_client import AtlassianClient
    AtlassianClient.save_token(email, token)
    console.print(f"[green]✓[/] Token saved for {email}. Set OAPW_ATLASSIAN_EMAIL={email} in your env.")


# ── generate sub-commands ─────────────────────────────────────────────────────

@generate_app.command("from-jira")
def generate_from_jira(
    ticket: str = typer.Argument(..., help="Jira ticket key, e.g. AUTH-42"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output directory for the generated test file"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override Ollama model"),
    no_kb: bool = typer.Option(False, "--no-kb", help="Skip knowledge base context retrieval"),
    mutate: int = typer.Option(0, "--mutate", help="Also generate N edge-case mutations (0 = disabled)"),
) -> None:
    """Generate a pytest test file from a Jira ticket."""
    asyncio.run(_generate_from_jira(ticket, out, model, not no_kb, mutate))


async def _generate_from_jira(
    ticket_key: str,
    out_dir: Optional[Path],
    model: Optional[str],
    use_kb: bool,
    mutate: int,
) -> None:
    from oapw.generators.from_jira import JiraTestGenerator
    gen = JiraTestGenerator(model=model, use_kb=use_kb)
    console.print(f"[bold]Generating test for[/] {ticket_key}…")
    result = await gen.generate(ticket_key, out_dir=out_dir)
    if not result.ok:
        console.print(f"[red]Error:[/] {result.error}")
        raise typer.Exit(1)
    if result.written:
        console.print(f"[green]✓[/] Written: {result.path}")
    else:
        console.print(result.test.code)

    if mutate > 0 and result.test.code:
        from oapw.generators.mutator import EdgeCaseMutator
        console.print(f"[bold]Generating {mutate} edge-case mutation(s)…[/]")
        mutator = EdgeCaseMutator(model=model)
        mutations = await mutator.mutate(result.test, count=mutate)
        if out_dir:
            paths = mutator.write_mutations(mutations, out_dir=out_dir)
            for p in paths:
                console.print(f"  [green]✓[/] {p}")
        else:
            for m in mutations:
                console.print(f"\n[bold]# Mutation: {m.mutation_type}[/] — {m.description}")
                console.print(m.code)


@generate_app.command("from-story")
def generate_from_story(
    story: str = typer.Argument(..., help="User story text, e.g. 'As a user I want to reset my password'"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output directory"),
    feature: Optional[str] = typer.Option(None, "--feature", "-f", help="Short feature name for the filename"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override Ollama model"),
    no_kb: bool = typer.Option(False, "--no-kb", help="Skip knowledge base context retrieval"),
) -> None:
    """Generate a pytest test file from a plain-text user story."""
    asyncio.run(_generate_from_story(story, out, feature or "", model, not no_kb))


async def _generate_from_story(
    story: str,
    out_dir: Optional[Path],
    feature_name: str,
    model: Optional[str],
    use_kb: bool,
) -> None:
    from oapw.generators.from_user_story import UserStoryGenerator
    gen = UserStoryGenerator(model=model, use_kb=use_kb)
    console.print("[bold]Generating test from user story…[/]")
    result = await gen.generate(story, feature_name=feature_name, out_dir=out_dir)
    if not result.ok:
        console.print(f"[red]Error:[/] {result.error}")
        raise typer.Exit(1)
    if result.written:
        console.print(f"[green]✓[/] Written: {result.path}")
    else:
        console.print(result.test.code)


@generate_app.command("smoke")
def generate_smoke(
    url: str = typer.Argument(..., help="Base URL to crawl, e.g. http://localhost:3000"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output directory"),
    max_pages: int = typer.Option(10, "--max-pages", help="Maximum pages to crawl"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override Ollama model"),
) -> None:
    """Crawl a live URL and generate smoke tests for discovered pages."""
    asyncio.run(_generate_smoke(url, out, max_pages, model))


async def _generate_smoke(
    url: str,
    out_dir: Optional[Path],
    max_pages: int,
    model: Optional[str],
) -> None:
    from oapw.generators.crawler import SmokeTestCrawler
    crawler = SmokeTestCrawler(model=model)
    console.print(f"[bold]Crawling[/] {url} (max {max_pages} pages)…")
    results = await crawler.crawl_and_generate(url, max_pages=max_pages, out_dir=out_dir)
    for r in results:
        if r.written:
            console.print(f"[green]✓[/] {r.path}")
        elif r.error:
            console.print(f"[red]✗[/] {r.test.test_name}: {r.error}")
        else:
            console.print(f"\n[bold]{r.test.test_name}[/]")
            console.print(r.test.code)


# ── version ───────────────────────────────────────────────────────────────────

@app.command()
def version() -> None:
    """Print the oapw version."""
    console.print(f"oapw [bold]{__version__}[/]")


if __name__ == "__main__":
    app()
