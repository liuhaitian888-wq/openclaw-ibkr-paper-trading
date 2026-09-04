import os
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path

def rotate_jsonl(file_path: Path, max_size_mb: int = 100, retention_days: int = 14):
    """Rotates a JSONL file if it exceeds max_size_mb and cleans up old ones."""
    if not file_path.exists():
        return

    # 1. Check size and rotate
    if file_path.stat().st_size > max_size_mb * 1024 * 1024:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        rotated_path = file_path.with_name(f"{file_path.stem}_{timestamp}{file_path.suffix}.gz")
        
        print(f"Rotating {file_path.name} to {rotated_path.name}...")
        with file_path.open('rb') as f_in:
            with gzip.open(rotated_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Clear original file
        file_path.write_text("")

    # 2. Retention cleanup
    cleanup_old_files(file_path.parent, file_path.stem, retention_days)

def cleanup_old_files(directory: Path, prefix: str, retention_days: int):
    cutoff = datetime.now() - timedelta(days=retention_days)
    for path in directory.glob(f"{prefix}_*.gz"):
        try:
            # Extract timestamp from filename
            ts_str = path.stem.split('_')[-1].replace('.jsonl', '')
            file_ts = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
            if file_ts < cutoff:
                print(f"Removing old log: {path.name}")
                path.unlink()
        except (ValueError, IndexError):
            continue

def check_disk_usage(path: Path, min_free_gb: int = 5):
    """Checks free disk space and returns True if okay."""
    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024**3)
    if free_gb < min_free_gb:
        print(f"WARNING: Low disk space! {free_gb:.2f} GB free on {path}.")
        return False
    return True
