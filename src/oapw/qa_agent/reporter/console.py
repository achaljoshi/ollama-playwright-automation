"""ConsoleReporter — prints a rich QA run summary to stdout.

Produces a human-readable report matching the example in PLAN.md §7.5.
Uses Rich for colour and tables when available (gracefully degrades to
plain text if Rich is not installed).

Usage::

    reporter = ConsoleReporter()
    reporter.report(qa_run_result)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oapw.qa_agent.models import QaRunResult, TestRunResult


class ConsoleReporter:
    """Prints a QA run summary to stdout using Rich (or plain text fallback)."""

    def report(self, result: "QaRunResult") -> None:
        """Print the full run summary for *result*."""
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table
            from rich import box

            self._rich_report(result, Console())
        except ImportError:
            self._plain_report(result)

    # ── Rich rendering ────────────────────────────────────────────────────────

    def _rich_report(self, result: "QaRunResult", console: object) -> None:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich import box

        c: Console = console  # type: ignore[assignment]

        # Header
        c.print(
            Panel(
                f"[bold]Goal:[/bold] {result.goal.raw}\n"
                f"[bold]Scope:[/bold] {result.goal.scope.value}  "
                f"[bold]Env:[/bold] {result.environment or 'default'}",
                title="QA Agent Run",
                expand=False,
            )
        )

        # Per-test table
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        table.add_column("Test", style="white", min_width=30)
        table.add_column("Status", justify="center", min_width=8)
        table.add_column("Time", justify="right", min_width=8)
        table.add_column("Judgment", min_width=14)

        for t in result.tests_run:
            status = "[green]✓ PASS[/]" if t.passed else "[red]✗ FAIL[/]"
            duration = f"{t.duration_ms:.0f}ms"
            judgment = ""
            if t.judgment:
                cl = t.judgment.classification.value
                cf = t.judgment.confidence
                color = "green" if cl == "pass" else ("red" if cl == "real_bug" else "yellow")
                judgment = f"[{color}]{cl}[/] ({cf:.0%})"
            table.add_row(t.test_name, status, duration, judgment)

        c.print(table)

        # Summary line
        color = "green" if result.failed == 0 else "red"
        c.print(
            f"\n[{color}][bold]{result.passed}/{result.total} passed[/bold][/]  "
            f"({result.duration_ms:.0f}ms total)"
        )

        # Failures detail
        failures = [t for t in result.tests_run if not t.passed]
        for t in failures:
            c.rule(f"[red]{t.test_name}[/]")
            if t.error:
                c.print(f"  [dim]Error:[/] {t.error[:200]}")
            if t.judgment:
                j = t.judgment
                c.print(f"  [bold]🧠 Judgment:[/] {j.classification.value} (confidence: {j.confidence:.0%})")
                if j.hypothesis:
                    c.print(f"  [dim]Hypothesis:[/] {j.hypothesis}")
                for ev in j.evidence:
                    c.print(f"  [dim]• {ev}[/]")
                c.print(f"  [bold]🎯 Suggested action:[/] {j.suggested_action.value}")
            if t.investigation:
                inv = t.investigation
                if inv.jira_draft_title:
                    c.print(f"\n  [bold cyan]📝 Draft bug:[/] {inv.jira_draft_title}")
                if inv.related_jira:
                    c.print(f"  [dim]Related:[/] {', '.join(inv.related_jira)}")

        c.print("")

    # ── Plain-text fallback ───────────────────────────────────────────────────

    def _plain_report(self, result: "QaRunResult") -> None:
        print(f"\n=== QA Agent Run: {result.goal.raw} ===")
        print(f"Scope: {result.goal.scope.value}  Env: {result.environment or 'default'}\n")

        for t in result.tests_run:
            status = "PASS" if t.passed else "FAIL"
            print(f"  [{status}] {t.test_name}  ({t.duration_ms:.0f}ms)")

        print(f"\n{result.passed}/{result.total} passed  ({result.duration_ms:.0f}ms total)\n")

        for t in result.tests_run:
            if not t.passed:
                print(f"\n--- {t.test_name} ---")
                if t.error:
                    print(f"  Error: {t.error[:200]}")
                if t.judgment:
                    j = t.judgment
                    print(f"  Judgment: {j.classification.value} ({j.confidence:.0%})")
                    if j.hypothesis:
                        print(f"  Hypothesis: {j.hypothesis}")
