"""Headless runner for Windows Task Scheduler:  python run_report.py user_data\\jobs\\my-job.yaml"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from variance.scheduled import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
