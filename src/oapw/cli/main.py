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

# ── Sub-app groups (populated by other modules as framework grows) ────────────
cache_app = typer.Typer(name="cache", help="Cache management commands", no_args_is_help=True)
app.add_typer(cache_app)


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


# ── version ───────────────────────────────────────────────────────────────────

@app.command()
def version() -> None:
    """Print the oapw version."""
    console.print(f"oapw [bold]{__version__}[/]")


if __name__ == "__main__":
    app()
