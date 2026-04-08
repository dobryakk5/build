from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path


def current_week_stamp() -> str:
    now = datetime.now()
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


class WeeklyLogWriter:
    def __init__(self, log_dir: Path, log_name: str, keep_weeks: int) -> None:
        self.log_dir = log_dir
        self.log_name = log_name
        self.keep_weeks = keep_weeks
        self._current_stamp: str | None = None
        self._handle = None
        self._lock = threading.Lock()

    def _current_path(self) -> Path:
        return self.log_dir / f"{self.log_name}-{current_week_stamp()}.log"

    def _ensure_handle(self) -> None:
        stamp = current_week_stamp()
        if self._handle is not None and self._current_stamp == stamp:
            return

        self.log_dir.mkdir(parents=True, exist_ok=True)
        if self._handle is not None:
            self._handle.close()

        self._current_stamp = stamp
        self._handle = self._current_path().open("a", encoding="utf-8")
        self._cleanup()

    def _cleanup(self) -> None:
        log_files = sorted(
            self.log_dir.glob(f"{self.log_name}-*.log"),
            key=lambda path: path.name,
            reverse=True,
        )
        for old_file in log_files[self.keep_weeks:]:
            old_file.unlink(missing_ok=True)

    def write(self, message: str) -> None:
        if not message:
            return

        with self._lock:
            self._ensure_handle()
            assert self._handle is not None
            self._handle.write(message)
            self._handle.flush()

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.close()
                self._handle = None


def stream_output(stream, mirror, writer: WeeklyLogWriter) -> None:
    try:
        for chunk in iter(stream.readline, ""):
            if not chunk:
                break
            mirror.write(chunk)
            mirror.flush()
            writer.write(chunk)
    finally:
        stream.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a command and write weekly rotated logs.")
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--log-name", required=True)
    parser.add_argument("--keep-weeks", type=int, default=12)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        raise SystemExit("Command is required after --")

    writer = WeeklyLogWriter(Path(args.log_dir), args.log_name, args.keep_weeks)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=os.environ.copy(),
    )

    stdout_thread = threading.Thread(
        target=stream_output,
        args=(process.stdout, sys.stdout, writer),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=stream_output,
        args=(process.stderr, sys.stderr, writer),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    try:
        return_code = process.wait()
        stdout_thread.join()
        stderr_thread.join()
        return return_code
    except KeyboardInterrupt:
        process.terminate()
        return process.wait()
    finally:
        writer.close()


if __name__ == "__main__":
    raise SystemExit(main())
