# NYXUS AI v1.0.0 — Final Release Document

Prepared 2026-07-20. This is the authoritative release record for NYXUS AI
v1.0.0: what shipped, how it's built, its measured performance (from both
the Sprint 9 baseline and the Sprint-9.5-adjacent large-scale stress test),
its known limitations, and the V2 roadmap. **As of this release, V1 is
frozen: no new features, only critical bug fixes. All new feature work
belongs to V2.**

---

## 1. Features included

- **Semantic search** over local files by natural-language description
  (not filename), using sentence-transformer embeddings + cosine similarity,
  with per-result match reasons.
- **Supported file types**: images (jpg/jpeg/png/bmp/webp) via a vision
  captioning + tagging pipeline (BLIP + MobileNetV2) and OCR (Tesseract,
  English + Hebrew), plus text-bearing documents (pdf, pptx, docx, xlsx).
- **Background indexing**: parallel (thread-pool) extraction/OCR/vision with
  batched embedding computation, ~2.85x faster than the original sequential
  implementation (see §3). Fully responsive UI throughout — Pause/Resume/
  Cancel controls, live progress reporting.
- **Automatic, self-aware pausing**: indexing pauses itself (and shows why)
  under high CPU usage from *other* processes, high RAM usage, Battery Saver,
  low battery, or a fullscreen app/game/presentation — resuming automatically
  once conditions clear.
- **Result cards** with inline Open / Reveal in Folder / Copy Path / Rename /
  Delete actions (also via right-click); Delete moves to the Recycle Bin,
  never a permanent delete, with the index updated immediately.
- **Search history**: recent searches shown in a dedicated panel, re-runnable
  with a double-click, clearable, entirely local (never transmitted).
- **Theming**: Light, Dark, and System (follows the OS theme live).
- **Version + About**: Help > About NYXUS AI shows the current version and
  third-party attributions.
- **Crash logging**: uncaught exceptions in the frozen, windowed build are
  written to `%APPDATA%\MemoryOS\crash.log` instead of being silently lost.
- **Windows installer**: per-user install (no admin rights needed), Start
  Menu/Desktop shortcuts, clean uninstall with an explicit, opt-in prompt to
  also delete the user's search index and history (default: preserved).
- **Legacy CLI** (`memoryos.cli.main`): the original PoC's terminal-based
  search tool, kept working as a verified fallback with its own independent
  `.index/` cache. Retirement remains explicitly deferred to a future
  project, not part of V1's scope.

## 2. Architecture summary

- **UI**: PySide6/Qt6 (`memoryos/ui/`) — `QMainWindow` shell, custom
  `ResultCard`/`ResultsView` widgets, `EmptyState`, `SearchHistoryPanel`,
  QSS-based light/dark stylesheets, Fusion-style dark palette for native Qt
  chrome.
- **Indexing** (`memoryos/indexing.py`): a `DatabaseIndexer` driving a
  bounded `ThreadPoolExecutor` (`DEFAULT_MAX_WORKERS = min(max(1, cpu_count-1), 8)`)
  for per-file extraction/OCR/vision (no DB access on worker threads), with a
  single coordinating thread performing all SQLite writes and batched
  `encode()` calls (`EMBEDDING_BATCH_SIZE = 16`). Runs on a dedicated `QThread`
  (`memoryos/background/worker.py`) so the UI thread is never blocked.
- **Storage**: SQLite via stdlib `sqlite3`, WAL mode, single-writer-thread
  invariant (each `Database` connection is created and used only on the
  thread that owns it). Embedding storage is exposed through a narrow
  interface (`upsert_file`/`get_by_path`/`delete_missing`) specifically so it
  can be swapped for an ANN-backed store (e.g. FAISS/LanceDB) in V2 without
  touching calling code — the Non-Negotiable Architecture Rule this project
  was built under.
- **Search**: brute-force cosine similarity against all stored embeddings
  (`memoryos/search/engine.py`) — adequate at today's scale (see §7 for the
  V2 consideration at much larger scale).
- **Background health**: `ResourceMonitor` + `PowerStateProvider`
  (`memoryos/background/`) sample system CPU/RAM/battery/fullscreen state and
  attribute CPU usage correctly (excluding NYXUS AI's own indexing load) to
  decide when to auto-pause.
- **Packaging**: PyInstaller onedir build (`packaging/memoryos.spec`,
  windowed/`console=False`, offline model cache bundled) wrapped in an Inno
  Setup 6 installer (`packaging/memoryos.iss`, per-user install, stable
  AppId GUID `2B720FD5-B1CC-462F-80FF-B4B8A5EB8528`).
- **Privacy**: entirely offline-first — no user data (files, embeddings,
  search history, queries) is ever transmitted anywhere.

## 3. Performance baseline (131-file real corpus, from source)

Full detail in `PERFORMANCE_BASELINE.md`; summarized here:

| Metric | Result |
|---|---|
| Startup time | ~9.5s (cold, all models loading) |
| Indexing speedup (parallel vs. sequential) | 2.85x (664.6s → 233.1s) |
| Search latency | ~32-57ms/query |
| CPU during indexing | avg 257.2% (~2.6 cores), peak 821.9% (~8.2 cores) |
| RAM during indexing | avg 2,855 MB, peak 3,157 MB |

## 4. Stress test at scale (5,000 / 10,000 files)

Measured 2026-07-20 to evaluate behavior well beyond the 131-file baseline.

### Methodology — read this before the numbers below

A true 5,000-10,000 file test using real images (like the 131-file baseline
corpus) would take an estimated **2.5-5 hours** of wall-clock time: OCR +
vision model inference cost is roughly constant per image regardless of
corpus size, so it doesn't get cheaper at scale, and 10,000 real images at
the measured ~1.78s/file parallel rate is just genuinely that slow.

Given that, this stress test uses a **lightweight but real** corpus instead:
10,000 real `.docx` files (via `python-docx`, varied text content, no
embedded images), generated and indexed through the actual, unmodified
`DatabaseIndexer`/embedding/database code — real extraction, real thread
pool, real SQLite writes, real search engine. What this **does** measure:
extraction + parallel threading + database + embedding-batching + search
overhead at real scale. What it **does not** measure: OCR/vision inference
cost at scale, since these files have no embedded images to trigger it — a
real-world folder of 5,000-10,000 photos would be dominated by that cost
instead, and is separately projected (not measured) below.

### Indexing throughput

| Files | Time | Per-file rate |
|---|---|---|
| 300 (calibration) | 12.5s | 41.6 ms/file |
| 5,000 | 211.2s (3.5 min) | 42.2 ms/file |
| 10,000 | 425.0s (7.1 min) | 42.5 ms/file |

Zero indexing errors at any scale. The per-file rate is essentially flat
from 300 to 10,000 files (41.6 → 42.5 ms/file) — no quadratic blowup or
other scaling cliff observed in the extraction/threading/database pipeline
at this range.

### CPU / memory usage

Sampled every ~1s throughout each run:

| Files | CPU avg (% of one core) | CPU peak | RAM avg | RAM peak |
|---|---|---|---|---|
| 5,000 | 1585.0% (~15.9 cores) | 1622.7% | 2,025 MB | 2,590 MB |
| 10,000 | 1587.0% (~15.9 cores) | 1626.6% | 2,479 MB | 3,610 MB |

CPU usage is much higher here than the image-heavy baseline's ~2.6-8.2 cores
(§3) — expected, and not a regression. For image-heavy corpora, the *worker
pool* (OCR/vision, deliberately capped at 8 threads, each pinned to 1
internal PyTorch thread) dominates CPU. For this text-only corpus,
extraction is nearly free, so the *coordinator thread's* embedding-batch
calls — which are **not** thread-count-limited the way the worker pool is —
become the dominant cost instead, and a single batched `encode()` call can
burst across many cores on this machine. Both are working as designed;
which one dominates just depends on the corpus's file type mix.

RAM stays lower than the image-heavy baseline (no BLIP/MobileNetV2/Tesseract
loaded, since this corpus never touches OCR/vision) and grows only modestly
from 5,000 to 10,000 rows (2,025 MB → 2,479 MB average) — consistent with
holding roughly twice the data, not a leak.

### Search latency at scale

Measured against the fully-populated database immediately after each run:

| Files in DB | Query 1 | Query 2 | Query 3 |
|---|---|---|---|
| 131 (baseline) | ~32-57ms | — | — |
| 5,000 | 144.4ms | 97.9ms | 90.9ms |
| 10,000 | 211.1ms | 1286.6ms* | 173.5ms |

*Flagged and investigated: re-running that exact query six times back-to-back
immediately afterward gave 179.0/179.4/182.8ms — consistent with the other
two queries at that scale, not 1286.6ms. The one high reading was a
non-reproducible system blip (background process or GC pause) during that
specific moment of the original run, not a real cost difference tied to the
query or a scaling problem. The trustworthy number for 10,000 rows is
**~170-210ms**, not the outlier.

Search time grows with corpus size as expected for a brute-force cosine-
similarity comparison against every stored embedding (no approximate-nearest-
neighbor index) — roughly 131 rows → ~150-800x fewer comparisons than 10,000
rows, and latency scales accordingly, though sub-linearly in practice (going
from 5,000 to 10,000 rows, a 2x increase, cost roughly 1.5-2x, not more).

### Projected (not measured) time for an image-heavy corpus at this scale

Extrapolated from the real, measured 131-file image-heavy baseline
(233.1s / 131 files = 1.779s/file, parallel, §3):

| Files | Projected time |
|---|---|
| 5,000 | ~8,900s (~2.5 hours) |
| 10,000 | ~17,800s (~4.9 hours) |

This is a linear projection from a much smaller sample, not a fresh
measurement — real behavior at that scale (e.g. thermal throttling over a
multi-hour run, disk I/O contention from bundled-model-cache reads, or
memory pressure from holding tens of thousands of embeddings) could differ
in either direction. If a genuine multi-hour real-image stress test is ever
wanted, this is the number to compare it against.

## 5. Known limitations

- **No code signing**: the installer and frozen exe show a Windows
  SmartScreen "unknown publisher" warning (no certificate available) — a
  disclosed, known limitation, not a defect.
- **Brute-force search**: no approximate-nearest-neighbor index; search
  latency scales with corpus size (see §4). Fine through at least 10,000
  files (~170-210ms); worth revisiting if real-world corpora regularly
  exceed ~100,000 files.
- **No real-hardware battery-saver/fullscreen testing**: `PowerStateProvider`
  is verified with mocks only; no alternate hardware was available to
  confirm real OS-level battery/fullscreen signal behavior.
- **Legacy CLI + JSON/NumPy `IndexStore` retained**: `memoryos/cli/` and
  `memoryos/index/store.py` remain in the codebase as a verified fallback,
  with their own independent `.index/` cache. Not yet retired — deferred to
  a future, separate removal project.
- **Stress test doesn't cover image-heavy corpora at scale**: the 5,000/
  10,000-file stress test used lightweight real `.docx` files, not real
  images, so OCR/vision cost at that scale is projected (§4), not measured.
- **Single-machine measurements**: all performance numbers (baseline and
  stress test) come from one development machine; absolute numbers will
  vary by hardware, though the throughput/latency shape should generalize.

## 6. Future V2 roadmap

- Retire the legacy CLI (`memoryos/cli/`) and JSON/NumPy `IndexStore`
  (`memoryos/index/store.py`) once the SQLite-backed path has enough
  production mileage to fully replace it.
- Evaluate an ANN index (FAISS or LanceDB) behind the existing narrow
  embedding-storage interface (`upsert_file`/`get_by_path`/`delete_missing`)
  if real-world corpora grow well past 10,000-100,000+ files and brute-force
  search latency becomes a genuine complaint.
- Code signing certificate to remove the SmartScreen "unknown publisher"
  warning.
- Re-measure the performance baseline against the shipped frozen/installed
  build specifically (current baseline is from-source; the frozen build's
  underlying logic is identical, but it hasn't been independently
  re-measured).
- Consider a genuine multi-hour real-image stress test at 5,000-10,000
  files if a use case emerges that needs firmer numbers than the current
  linear projection (§4).

## 7. Exact dependency versions

Python 3.12.10. Full pinned set (also see `requirements.txt`):

```
altgraph==0.17.5
annotated-doc==0.0.4
anyio==4.14.2
certifi==2026.6.17
click==8.4.2
colorama==0.4.6
et_xmlfile==2.0.0
filelock==3.29.0
fsspec==2026.4.0
h11==0.16.0
hf-xet==1.5.2
httpcore==1.0.9
httpx==0.28.1
huggingface_hub==1.24.0
idna==3.18
iniconfig==2.3.0
Jinja2==3.1.6
joblib==1.5.3
lxml==6.1.1
markdown-it-py==4.2.0
MarkupSafe==3.0.3
mdurl==0.1.2
mpmath==1.3.0
narwhals==2.24.0
networkx==3.6.1
numpy==2.5.1
openpyxl==3.1.5
packaging==26.2
pefile==2024.8.26
pillow==12.3.0
pluggy==1.6.0
psutil==7.2.2
Pygments==2.20.0
pyinstaller==6.21.0
pyinstaller-hooks-contrib==2026.6
pymupdf==1.28.0
PySide6==6.11.1
PySide6_Addons==6.11.1
PySide6_Essentials==6.11.1
pytesseract==0.3.13
pytest==9.1.1
python-docx==1.2.0
python-pptx==1.0.2
pywin32-ctypes==0.2.3
PyYAML==6.0.3
regex==2026.7.10
rich==15.0.0
safetensors==0.8.0
scikit-learn==1.9.0
scipy==1.18.0
Send2Trash==2.1.0
sentence-transformers==5.6.0
setuptools==78.1.0
shellingham==1.5.4
shiboken6==6.11.1
sympy==1.14.0
threadpoolctl==3.6.0
tokenizers==0.22.2
torch==2.13.0+cpu
torchvision==0.28.0+cpu
tqdm==4.69.0
transformers==5.14.1
typer==0.27.0
typing_extensions==4.15.0
xlsxwriter==3.2.9
```

External (non-pip) dependencies: Tesseract OCR (system-wide, with English +
Hebrew tessdata bundled in `tessdata/`), Inno Setup 6 (build-time only, not
a runtime dependency).

## 8. Final project statistics

| Metric | Value |
|---|---|
| Python source files (`memoryos/`) | 55 |
| Lines of source code (`memoryos/`) | 3,364 |
| Test files | 11 |
| Lines of test code | 1,385 |
| Total tests | 92 (all passing) |
| Frozen build size (`dist/NyxusAI/`) | ~4.5 GB (bundles Python runtime, Tesseract, and all model weights for fully offline operation) |
| Installer size | ~3.23 GB (3,231,113,249 bytes) |

## 9. Installer checksum

`packaging/installer_output/NyxusAI-Setup-1.0.0.exe`:

```
SHA256: c50c33c728d01a0429d2541cd95318c56373d4724ff89d76f3e1c7b5e65f0ea3
```

---

## V1 is now frozen

Per project direction as of this release: **no new features will be added
to V1 from this point onward. Only critical bug fixes are permitted.** All
future feature development belongs to V2.
