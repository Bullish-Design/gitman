#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "watchdog>=4.0",
#     "pydantic>=2.0",
#     "rich>=13.7",
#     "python-dotenv>=1.0",
#     "requests>=2.32",
# ]
# ///
"""
Watchdog-based monitor for GitHub webhook JSONL files.
Parses new entries and emits events.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Set
from dataclasses import dataclass, field
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from rich import print as rprint
from rich.console import Console

from src.gitman.models.utils import GitHubWebhookParser
from src.gitman.models.webhook_models import WebhookEvent

console = Console()


@dataclass
class ProcessedState:
    """Tracks processed lines per file."""
    file_lines: Dict[str, int] = field(default_factory=dict)
    last_modified: Dict[str, float] = field(default_factory=dict)
    
    def get_processed_lines(self, filename: str) -> int:
        """Get number of processed lines for a file."""
        return self.file_lines.get(filename, 0)
    
    def set_processed_lines(self, filename: str, count: int) -> None:
        """Set number of processed lines for a file."""
        self.file_lines[filename] = count
        self.last_modified[filename] = time.time()
    
    def save_state(self, state_file: Path) -> None:
        """Save state to JSON file."""
        data = {
            'file_lines': self.file_lines,
            'last_modified': self.last_modified
        }
        state_file.write_text(json.dumps(data, indent=2))
    
    @classmethod
    def load_state(cls, state_file: Path) -> ProcessedState:
        """Load state from JSON file."""
        if not state_file.exists():
            return cls()
        
        try:
            data = json.loads(state_file.read_text())
            return cls(
                file_lines=data.get('file_lines', {}),
                last_modified=data.get('last_modified', {})
            )
        except (json.JSONDecodeError, KeyError):
            return cls()


class WebhookEventEmitter:
    """Emits parsed webhook events."""
    
    def __init__(self):
        self.event_count = 0
    
    def emit_event(self, event: WebhookEvent, filename: str, 
                   line_num: int) -> None:
        """Emit a parsed webhook event."""
        self.event_count += 1
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # Extract key info based on event type
        event_info = self._extract_event_info(event)
        
        rprint(
            f"[bold green]{timestamp:^10}[/bold green] "
            f"[cyan]{filename:^30}[/cyan]:{line_num:^4} "
            f"[yellow]{type(event).__name__:^15}[/yellow] "
            f"{event_info}"
        )
    
    def _extract_event_info(self, event: WebhookEvent) -> str:
        """Extract relevant info from event for display."""
        if hasattr(event, 'issue'):
            return f"#{event.issue.number} '{event.issue.title}'"
        elif hasattr(event, 'discussion'):
            return f"#{event.discussion.number} '{event.discussion.title}'"
        elif hasattr(event, 'workflow_run'):
            return f"'{event.workflow_run.name}' -> {event.workflow_run.status}"
        elif hasattr(event, 'check_run'):
            return f"'{event.check_run.name}' -> {event.check_run.status}"
        elif hasattr(event, 'commits'):
            commit_count = len(event.commits)
            return f"{commit_count} commit{'s' if commit_count != 1 else ''}"
        else:
            return f"action: {getattr(event, 'action', 'unknown')}"


class JsonlFileHandler(FileSystemEventHandler):
    """Handles JSONL file changes."""
    
    def __init__(self, logs_dir: Path, state_file: Path):
        self.logs_dir = logs_dir
        self.state_file = state_file
        self.parser = GitHubWebhookParser()
        self.emitter = WebhookEventEmitter()
        self.state = ProcessedState.load_state(state_file)
        
        # Process existing files on startup
        self._process_existing_files()
    
    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        if file_path.suffix == '.jsonl':
            self._process_file(file_path)
    
    def on_created(self, event):
        """Handle file creation events."""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        if file_path.suffix == '.jsonl':
            self._process_file(file_path)
    
    def _process_existing_files(self) -> None:
        """Process any existing JSONL files on startup."""
        for jsonl_file in self.logs_dir.glob('*.jsonl'):
            self._process_file(jsonl_file)
    
    def _process_file(self, file_path: Path) -> None:
        """Process new lines in a JSONL file."""
        if not file_path.exists():
            return
        
        filename = file_path.name
        processed_lines = self.state.get_processed_lines(filename)
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Process only new lines
            new_lines = lines[processed_lines:]
            if not new_lines:
                return
            
            new_events = 0
            for i, line in enumerate(new_lines):
                line = line.strip()
                if not line:
                    continue
                
                line_num = processed_lines + i + 1
                try:
                    event = self.parser.parse_webhook_event(line)
                    self.emitter.emit_event(event, filename, line_num)
                    new_events += 1
                except ValueError as e:
                    # Skip non-webhook data or unparseable lines
                    if "Non-webhook data" not in str(e):
                        console.print(
                            f"[red]Parse error[/red] {filename}:{line_num}: {e}"
                        )
                except Exception as e:
                    console.print(
                        f"[red]Error[/red] {filename}:{line_num}: {e}"
                    )
            
            # Update processed line count
            self.state.set_processed_lines(filename, len(lines))
            self.state.save_state(self.state_file)
            
            if new_events > 0:
                console.print(
                    f"[dim]Processed {new_events} new events from "
                    f"{filename}[/dim]"
                )
                
        except Exception as e:
            console.print(f"[red]File error[/red] {filename}: {e}")


class WebhookWatcher:
    """Main webhook file watcher."""
    
    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.state_file = logs_dir / '.webhook_watcher_state.json'
        self.observer = Observer()
        self.handler = JsonlFileHandler(logs_dir, self.state_file)
    
    def start(self) -> None:
        """Start watching for file changes."""
        if not self.logs_dir.exists():
            console.print(
                f"[red]Error:[/red] Logs directory {self.logs_dir} "
                f"does not exist"
            )
            return
        
        console.print(
            f"[green]Starting webhook watcher[/green] on "
            f"{self.logs_dir}"
        )
        
        self.observer.schedule(
            self.handler, 
            path=str(self.logs_dir), 
            recursive=False
        )
        self.observer.start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def stop(self) -> None:
        """Stop watching for file changes."""
        console.print("\n[yellow]Stopping webhook watcher...[/yellow]")
        self.observer.stop()
        self.observer.join()
        console.print(
            f"[green]Processed {self.handler.emitter.event_count} "
            f"total events[/green]"
        )


def main() -> None:
    """Main entry point."""
    # Look for .gitman directory structure
    current_dir = Path.cwd()
    gitman_dir = current_dir / '.gitman'
    logs_dir = gitman_dir / 'logs'
    
    if not logs_dir.exists():
        console.print(
            f"[red]Error:[/red] Expected logs directory at {logs_dir}"
        )
        console.print(
            "[dim]Make sure you're in a directory with .gitman/logs/[/dim]"
        )
        return
    
    watcher = WebhookWatcher(logs_dir)
    watcher.start()


if __name__ == '__main__':
    main()
