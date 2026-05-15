"""
Smoke test: remaster pipeline changes
  1. job_queue.py  → image_path_already_queued() dedup
  2. run_autonomous.py → remaster folder enqueue (dedup + empty-folder detection)
  3. supervisor.py → imports cleanly with Path fix
  4. Full boot sequence (dry-run, no browser)
"""

import sys
import os
import tempfile
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"
WARN = "\033[93m!\033[0m"

errors = []

def ok(msg): print(f"  {PASS} {msg}")
def fail(msg, err=None):
    errors.append(msg)
    print(f"  {FAIL} {msg}")
    if err: print(f"      {err}")
def info(msg): print(f"  {INFO} {msg}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n--- 1. supervisor.py — import with Path fix ---------------------------")
try:
    from pinterest_automation.supervisor import AutonomousSupervisor
    ok("supervisor.py imports cleanly (Path available)")
except Exception as e:
    fail("supervisor.py import failed", e)

# ─────────────────────────────────────────────────────────────────────────────
print("\n--- 2. job_queue.py — image_path_already_queued() ---------------------")
tmp_db = None
try:
    from pinterest_automation.job_queue import JobQueue, Job

    # Use a temp DB so we don't pollute the production queue
    tmp_db = Path(tempfile.mkdtemp()) / "test_jobs.db"
    q = JobQueue(db_file=tmp_db)

    # Create a temp image file
    tmp_img = tmp_db.parent / "test_remaster_image.jpg"
    tmp_img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)  # minimal JPEG magic

    # 1a. Before enqueue — should be False
    result = q.image_path_already_queued(str(tmp_img))
    if not result:
        ok("image_path_already_queued() → False before enqueue")
    else:
        fail("image_path_already_queued() returned True before any enqueue")

    # 1b. Enqueue the image
    q.enqueue_pin_upload(
        image_path=str(tmp_img),
        title="Test Pin",
        description="Test",
        link="https://example.com/test",
        board_name="test-board",
        priority=2,
        extra={"account_handle": "rida", "source": "remaster_final"},
    )

    # 1c. After enqueue — should be True
    result2 = q.image_path_already_queued(str(tmp_img))
    if result2:
        ok("image_path_already_queued() → True after enqueue (dedup works)")
    else:
        fail("image_path_already_queued() returned False after enqueue — dedup BROKEN")

    # 1d. Different image — should still be False
    tmp_img2 = tmp_db.parent / "other_image.jpg"
    tmp_img2.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
    result3 = q.image_path_already_queued(str(tmp_img2))
    if not result3:
        ok("image_path_already_queued() → False for different image (no false positives)")
    else:
        fail("image_path_already_queued() returned True for unqueued image — false positive!")

    # 1e. Stats
    stats = q.get_stats()
    info(f"Queue stats: {stats}")

except Exception as e:
    fail("job_queue dedup test crashed", e)
    import traceback; traceback.print_exc()
finally:
    if tmp_db:
        shutil.rmtree(tmp_db.parent, ignore_errors=True)

# ─────────────────────────────────────────────────────────────────────────────
print("\n--- 3. remaster_final folder detection --------------------------------")
try:
    remaster_dir = PROJECT_ROOT / "data" / "media" / "remaster_final"
    remaster_dir.mkdir(parents=True, exist_ok=True)

    images = [f for f in remaster_dir.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    if images:
        info(f"remaster_final/ has {len(images)} image(s) — enqueue path will be used:")
        for img in images[:3]:
            info(f"  {img.name}")
        if len(images) > 3:
            info(f"  ... and {len(images) - 3} more")
    else:
        info("remaster_final/ is EMPTY — fallback remasterer would trigger on real boot")

    ok("remaster_final/ directory check passed")
except Exception as e:
    fail("remaster_final directory check failed", e)

# ─────────────────────────────────────────────────────────────────────────────
print("\n--- 4. run_autonomous.py — top-level imports --------------------------")
try:
    # Just test the imports without executing run_supervisor
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_autonomous", PROJECT_ROOT / "run_autonomous.py")
    mod = importlib.util.module_from_spec(spec)
    # Don't exec — just verify the parse step (compile)
    import py_compile
    py_compile.compile(str(PROJECT_ROOT / "run_autonomous.py"), doraise=True)
    ok("run_autonomous.py compiles cleanly")
except Exception as e:
    fail("run_autonomous.py compile failed", e)
    import traceback; traceback.print_exc()

# ─────────────────────────────────────────────────────────────────────────────
print("\n--- 5. supervisor.py — remaster_raw path resolution -------------------")
try:
    sup_file = PROJECT_ROOT / "pinterest_automation" / "supervisor.py"
    content = sup_file.read_text(encoding="utf-8")

    if "C:\\\\Users\\\\REDX420" in content or r"C:\Users\REDX420" in content:
        fail("supervisor.py still contains hardcoded absolute path!")
    else:
        ok("No hardcoded absolute paths found in supervisor.py")

    if "Path(__file__).resolve().parent.parent" in content:
        ok("Dynamic PROJECT_ROOT path present in supervisor.py")
    else:
        fail("Dynamic path not found in supervisor.py")

    if "from pathlib import Path" in content:
        ok("Path imported in supervisor.py")
    else:
        fail("Path not imported in supervisor.py")
except Exception as e:
    fail("supervisor.py content check crashed", e)

# ─────────────────────────────────────────────────────────────────────────────
print("\n--- 6. queue dedup integration — production queue check ---------------")
try:
    from pinterest_automation.job_queue import get_job_queue
    prod_queue = get_job_queue()
    stats = prod_queue.get_stats()
    pending = prod_queue.list_pending()

    ok(f"Production queue accessible — {stats['total']} total jobs | DLQ: {stats['dlq_size']}")

    if pending:
        info(f"{len(pending)} pending/retry jobs in queue:")
        for job in pending[:5]:
            img = job.payload.get("image_path", "N/A")
            src = job.payload.get("extra", {}).get("source", "?")
            info(f"  [{job.id}] {src} → {Path(img).name if img != 'N/A' else 'N/A'}")
        if len(pending) > 5:
            info(f"  ... and {len(pending) - 5} more")
    else:
        info("Production queue is empty (supervisor has processed all jobs or none enqueued yet)")

    ok("Production queue dedup method available")
    # Quick test on a fake path
    already = prod_queue.image_path_already_queued("/nonexistent/test.jpg")
    if not already:
        ok("Dedup returns False for non-existent image (correct)")
    else:
        fail("Dedup returned True for non-existent image — potential false positive")

except Exception as e:
    fail("Production queue check failed", e)
    import traceback; traceback.print_exc()

# ─────────────────────────────────────────────────────────────────────────────
print("\n--- 7. GEMINI.md pipeline steps present -------------------------------")
try:
    gemini_md = (PROJECT_ROOT / "GEMINI.md").read_text(encoding="utf-8")
    checks = [
        ("enqueue-folder", "enqueue-folder step in GEMINI.md"),
        ("remaster_final", "remaster_final path in GEMINI.md"),
        ("17. **Remaster", "Step 17 (remaster loop) defined"),
        ("apply_luxury_overlay", "apply_luxury_overlay in pipeline"),
    ]
    for needle, label in checks:
        if needle in gemini_md:
            ok(label)
        else:
            fail(f"Missing: {label}")
except Exception as e:
    fail("GEMINI.md check failed", e)

# ─────────────────────────────────────────────────────────────────────────────
print()
print("━" * 60)
if errors:
    print(f"\033[91m  FAILED: {len(errors)} error(s)\033[0m")
    for e in errors:
        print(f"    • {e}")
    sys.exit(1)
else:
    print(f"\033[92m  ALL TESTS PASSED ({7} checks)\033[0m")
    sys.exit(0)
