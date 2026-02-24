#!/usr/bin/env python3
"""
Invoice Processing Pipeline — CLI Entry Point

Usage:
  python main.py process <pdf_file>          Process a single PDF
  python main.py process-all <folder>        Process all PDFs in a folder
  python main.py watch <folder>              Watch a folder and process new PDFs
  python main.py ui                          Launch the Streamlit web UI

Examples:
  python main.py process ../Invoices_1/invoice.pdf
  python main.py process-all ../Invoices_1/
  python main.py watch data/input/
  python main.py ui
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).parent))

from backend.config import INPUT_DIR, OUTPUT_DIR
from backend.pipeline.processor import run_pipeline, save_result

console = Console()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _check_api_key() -> None:
    from backend.config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        console.print(
            "[bold red]ERROR:[/bold red] ANTHROPIC_API_KEY is not set.\n"
            "Copy [italic].env.example[/italic] to [italic].env[/italic] and add your key.",
            highlight=False,
        )
        raise SystemExit(1)


def _process_one(pdf_path: Path, out_dir: Path) -> None:
    """Process a single PDF and print a summary table."""
    messages: list[str] = []

    def log(msg: str) -> None:
        messages.append(msg)
        console.print(f"  [dim]{msg}[/dim]")

    console.rule(f"[bold]{pdf_path.name}[/bold]")

    try:
        result = run_pipeline(pdf_path, progress_cb=log)
        out_path = save_result(result, out_dir)
    except Exception as exc:
        console.print(f"[bold red]FAILED:[/bold red] {exc}")
        return

    # Print summary table
    tbl = Table(title=f"Results — {result.supplier_name}", show_lines=True)
    tbl.add_column("Description", style="cyan", max_width=40)
    tbl.add_column("UOM", justify="center")
    tbl.add_column("Pack Qty", justify="right")
    tbl.add_column("$/EA", justify="right")
    tbl.add_column("Conf", justify="right")
    tbl.add_column("Escalate", justify="center")

    for item in result.line_items:
        esc_str = "[red]YES[/red]" if item.escalation_flag else "[green]no[/green]"
        conf_color = (
            "green" if item.confidence_score >= 0.80
            else "yellow" if item.confidence_score >= 0.50
            else "red"
        )
        tbl.add_row(
            item.item_description[:40],
            item.original_uom or "—",
            str(item.detected_pack_quantity or "—"),
            f"${item.price_per_base_unit:.4f}" if item.price_per_base_unit else "—",
            f"[{conf_color}]{item.confidence_score:.2f}[/{conf_color}]",
            esc_str,
        )

    console.print(tbl)
    console.print(
        f"[bold green]✓[/bold green] Output saved to [underline]{out_path}[/underline]"
    )
    s = result.summary
    console.print(
        f"  Items: {s['total_line_items']}  |  "
        f"Escalated: {s['escalated_items']}  |  "
        f"Avg confidence: {s['avg_confidence_score']:.2f}"
    )


# ─── Commands ─────────────────────────────────────────────────────────────────

@click.group()
def cli() -> None:
    """Invoice Processing Pipeline — extract & normalize line items from PDF invoices."""
    console.print(
        Panel.fit(
            "[bold blue]Invoice Processing Pipeline[/bold blue]\n"
            "[dim]Powered by Claude AI[/dim]",
            border_style="blue",
        )
    )


@cli.command()
@click.argument("pdf_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output-dir", "-o", default=None, type=click.Path(path_type=Path),
              help="Output directory (default: ./output)")
def process(pdf_file: Path, output_dir: Path | None) -> None:
    """Process a single PDF invoice."""
    _check_api_key()
    out_dir = output_dir or OUTPUT_DIR
    _process_one(pdf_file, out_dir)


@cli.command("process-all")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output-dir", "-o", default=None, type=click.Path(path_type=Path),
              help="Output directory (default: ./output)")
def process_all(folder: Path, output_dir: Path | None) -> None:
    """Process all PDF files found in FOLDER."""
    _check_api_key()
    out_dir = output_dir or OUTPUT_DIR
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        console.print(f"[yellow]No PDF files found in {folder}[/yellow]")
        return
    console.print(f"Found [bold]{len(pdfs)}[/bold] PDF(s) to process.")
    for pdf in pdfs:
        _process_one(pdf, out_dir)
    console.print(f"\n[bold green]All done![/bold green] Results in [underline]{out_dir}[/underline]")


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path),
                default=None, required=False)
@click.option("--output-dir", "-o", default=None, type=click.Path(path_type=Path),
              help="Output directory (default: ./output)")
def watch(folder: Path | None, output_dir: Path | None) -> None:
    """Watch FOLDER for new PDF files and process them automatically."""
    _check_api_key()
    watch_dir = folder or INPUT_DIR
    out_dir = output_dir or OUTPUT_DIR

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler, FileCreatedEvent
    except ImportError:
        console.print("[red]watchdog not installed. Run: pip install watchdog[/red]")
        raise SystemExit(1)

    class PDFHandler(FileSystemEventHandler):
        def on_created(self, event: FileCreatedEvent) -> None:
            if not event.is_directory and str(event.src_path).lower().endswith(".pdf"):
                pdf = Path(event.src_path)
                console.print(f"\n[bold yellow]New file detected:[/bold yellow] {pdf.name}")
                time.sleep(0.5)  # brief wait for write to complete
                _process_one(pdf, out_dir)

    observer = Observer()
    observer.schedule(PDFHandler(), str(watch_dir), recursive=False)
    observer.start()
    console.print(
        f"[bold green]Watching[/bold green] [underline]{watch_dir}[/underline] "
        f"for new PDFs. Press Ctrl+C to stop."
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    console.print("\n[dim]Watcher stopped.[/dim]")


@cli.command()
def ui() -> None:
    """Launch the Streamlit web UI."""
    import subprocess
    app_path = Path(__file__).parent / "frontend" / "app.py"
    console.print("[bold blue]Launching Streamlit UI…[/bold blue]")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path)],
        check=True,
    )


@cli.command("react-ui")
@click.option("--host", default="127.0.0.1", help="API server host")
@click.option("--port", default=8000, help="API server port")
def react_ui(host: str, port: int) -> None:
    """Launch the FastAPI backend for the React UI.

    Then in a second terminal:
      cd invoice_pipeline/frontend_react
      npm install   # first time only
      npm run dev
    """
    _check_api_key()
    import subprocess
    console.print(
        Panel.fit(
            f"[bold blue]API server → http://{host}:{port}[/bold blue]\n"
            "[dim]Open another terminal and run:[/dim]\n"
            "[yellow]  cd invoice_pipeline/frontend_react[/yellow]\n"
            "[yellow]  npm install   # first time only[/yellow]\n"
            "[yellow]  npm run dev[/yellow]",
            border_style="blue",
        )
    )
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "backend.api:app",
         "--host", host, "--port", str(port), "--reload"],
        check=True,
    )


if __name__ == "__main__":
    cli()
