# RankStein Gold Standard & Super-Turbo Configuration

This file contains the definitive technical specifications for the most stable and highest-velocity automation state achieved during the May 15, 2026 session.

## ⚡ Super-Turbo Performance Specs
| Variable | Value | Description |
|---|---|---|
| `PINTEREST_WORKER_COUNT` | `10` | Maximum parallel Chromium instances. |
| `PINTEREST_BASE_DELAY` | `0.1` | Near-zero delay between internal steps. |
| `PINTEREST_RATE_LIMIT_DELAY` | `0.5` | Minimal throttle between pin attempts. |
| `PINTEREST_HOURLY_LIMIT` | `5000` | High-volume hourly budget. |
| `PINTEREST_DAILY_LIMIT` | `100000` | Scaled daily budget for mass migration. |
| `PINTEREST_BURST_LIMIT` | `2000` | High-threshold burst allowance. |

## 🛠️ Interaction Logic (The "Gold Standard")
These logic patterns are hardcoded into `pinterest_driver.py` and `pinterest_batch_core.py`:
1. **Simplified Board Selection:** Always click the first visible option in the dropdown via JS. Bypasses search/type stalls.
2. **Aggressive Publishing:**
   - Click button with "Publish" or "Publicar" text (exclude "Save/Guardar").
   - If no redirect in 5s, send **Control+Enter**.
   - Detect success via SPA "View" button link or "Your Pin has been published!" toast.
3. **Draft Limit Management:** Automatic detection of "disabled" UI elements triggers a brute-force purge of the 50-draft limit.

## 🧼 Cleanup Protocols
- **Process Reset:** `taskkill /F /IM python.exe /T` followed by browser kills.
- **Lock Purge:** Deletion of `parent.lock`, `singletonlock`, and `lock` from all session directories.

## 📂 Reference Scripts
- `scripts/ops/restore_gold_config.py`: Resets system to these parameters.
- `scripts/ops/clear_pinterest_drafts.py`: Clears account bottlenecks.
- `scripts/ops/scale_automation.py`: Quickly toggles between 1, 6, and 10 workers.
