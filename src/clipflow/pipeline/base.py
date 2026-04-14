"""Base pipeline class — shared by tutorial (v1) and ugc (v2)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

from clipflow.project import ProjectSpec


class BasePipeline:
    """Base class for all ClipFlow pipelines."""

    def __init__(self, spec: ProjectSpec, console: Console | None = None):
        self.spec = spec
        self.console = console or Console()

    def run(self):
        """Run the full pipeline with progress display."""
        self._validate()

        # Save initial project spec
        spec_path = self.spec.save()
        self.console.print(f"[dim]Project spec → {spec_path}[/dim]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            task = progress.add_task("Running pipeline...", total=100)

            def on_progress(stage: str, message: str, pct: int):
                progress.update(task, completed=pct, description=f"[bold]{stage}[/bold]: {message}")

            self._run_stages(on_progress)

        # Save final project spec
        self.spec.save()
        self.console.print("\n[bold green]Pipeline complete.[/bold green]")

    def _validate(self):
        """Validate inputs. Override in subclass."""
        raise NotImplementedError

    def _run_stages(self, on_progress):
        """Run pipeline stages. Override in subclass."""
        raise NotImplementedError
