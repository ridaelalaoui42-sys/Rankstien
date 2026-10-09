"""Organize data/media/remaster_final into <blog>/<day>/<article_keyword>/ folders."""

import re
import shutil
from datetime import datetime
from pathlib import Path

BASE = Path("data/media/remaster_final")


def organize_remaster_final():
    files = [
        f for f in BASE.rglob("*") if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
    ]
    print(f"Found {len(files)} image files in {BASE}")

    moved_count = 0
    for f in files:
        rel = f.relative_to(BASE)
        parts = rel.parts

        # Check if already organized as blog/day/keyword/filename
        if len(parts) == 4 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[1]):
            continue

        # Extract blog handle
        blog = parts[0] if len(parts) > 1 else "recetadolce"

        # Extract date from directory name or fallback to mtime
        m_date = re.search(r"(202\d)(\d{2})(\d{2})", str(rel))
        if m_date:
            date_str = f"{m_date.group(1)}-{m_date.group(2)}-{m_date.group(3)}"
        else:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            date_str = mtime.strftime("%Y-%m-%d")

        # Extract article keyword from filename: e.g. <keyword>-source-01-viral-visual.jpg
        name = f.name
        kw = re.sub(r"-source-\d{2}-(?:viral-visual|recipe-card)\.[a-zA-Z0-9]+$", "", name)
        kw = re.sub(r"^remastered_v\d+_(?:[a-zA-Z0-9_-]+_)?", "", kw)
        kw = re.sub(r"[^a-zA-Z0-9_-]+", "-", kw).strip("-") or "general"

        target_dir = BASE / blog / date_str / kw
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f.name

        if f.resolve() != target_path.resolve():
            shutil.move(str(f), str(target_path))
            moved_count += 1

    # Cleanup empty directories
    for p in sorted(BASE.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p.is_dir() and not any(p.iterdir()):
            try:
                p.rmdir()
            except OSError:
                pass

    print(f"Organized {moved_count} files into blog/day/keyword folders.")


if __name__ == "__main__":
    organize_remaster_final()
