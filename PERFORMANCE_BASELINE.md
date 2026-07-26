# Zynora AI v1.0.0 — Performance Baseline

Measured 2026-07-20, running from source on the primary development machine
(many-core desktop CPU), against the real 131-file test corpus (`all test
data/`) used throughout Sprints 1-8.5's validation. These numbers exist as a
concrete reference point for judging future (V2) optimization work against —
"it feels faster" isn't good enough once there's a baseline to compare to.

Methodology notes are included alongside each number since a bare number
without context is easy to misread later.

## Startup time

**~9.5 seconds** from process start (embedding model, OCR engine, and vision
pipeline all loading fresh) to the main window shown and responsive.

- Measured from source, not the frozen build — the frozen build skips any
  Hugging Face Hub network probing entirely (`HF_HUB_OFFLINE=1`) but loads
  the same on-disk model weights, so the number should be close; it wasn't
  independently re-measured against the frozen exe this sprint.
- Almost entirely model-loading time (embedding model + BLIP captioner +
  MobileNetV2 tagger); the actual UI construction is a small fraction of this.

## Indexing throughput

**~2.85x speedup** from Sprint 8.5's parallel indexing work, measured as a
controlled, same-session, back-to-back comparison on the full 131-file real
corpus:

| Configuration | Time |
|---|---|
| Sequential (`max_workers=1`, `embedding_batch_size=1`) — pre-Sprint-8.5 equivalent | 664.6s |
| Parallel (`max_workers=7`, `embedding_batch_size=16`) — current default | 233.1s |

A repeated real-world run through the actual `MainWindow` (not the isolated
benchmark harness above) measured 241-277s for the same 131-file corpus —
consistent with the controlled number within normal machine-load variance.
Zero indexing errors in every run; identical top search results confirm
correctness was unaffected by parallelizing.

**Isolating embedding-batching's own contribution** (same worker count, batch
size 1 vs. 16, smaller 35-file mixed subset): negligible difference (60.8s
vs. 62.9s). For this corpus's actual bottleneck (OCR + vision, not the
embedding call), thread-pool parallelism is doing nearly all of the work;
batching would matter more for a lighter-per-file, much-larger corpus.

## Search latency

**~32-57ms per query**, end-to-end (embedding the query + cosine similarity
against 131 stored vectors + UI update), measured across three real queries
against the full indexed corpus. `perf_log`'s own internal timing (pure
search-engine time, excluding UI rendering) measured 31-37ms for the same
queries — both numbers are effectively instant relative to the original PoC's
3-second success bar.

## CPU / memory usage

Sampled every 0.5s throughout a full 131-file real indexing run (482 samples):

| | CPU (% of one core; 800% ≈ 8 cores) | RAM |
|---|---|---|
| Minimum | 3.0% | 1,251 MB |
| Average | 257.2% (~2.6 cores) | 2,855 MB |
| Peak | 821.9% (~8.2 cores) | 3,157 MB |

The peak (~8.2 cores) lines up with the `DEFAULT_MAX_WORKERS` cap of 8 — the
parallel design is using close to its intended ceiling at its busiest, not
silently under- or over-subscribing. RAM footprint is dominated by the three
loaded ML models (embedding, OCR, vision) rather than indexing activity
itself — it doesn't grow materially over the course of a run.

During a light workload (three back-to-back searches against the already-
loaded models, no indexing in progress): CPU spiked briefly to ~516% for the
embedding calls, settling at idle afterward; RAM held steady at ~2,722 MB
(same loaded-models floor as above).

## Known caveats for anyone comparing future numbers against this baseline

- All numbers here are from-source, not the final frozen/installed build —
  re-measuring against the shipped installer would be a reasonable V2 sanity
  check, though the underlying Python logic is identical either way.
- `perf_log`'s own `cpu_percent` column for indexing runs is a *point-in-time*
  snapshot taken once at completion (`psutil.cpu_percent(interval=None)`),
  not a run-average — it can read misleadingly close to 0% depending on what
  the CPU happened to be doing in the instant before the snapshot. The
  min/avg/peak figures above (from periodic sampling throughout the run) are
  the trustworthy numbers; don't read `perf_log`'s raw `cpu_percent` column
  for past runs as "average CPU used."
- Single-machine, single-run-per-configuration measurements (a few repeated
  for the controlled sequential-vs-parallel comparison) — real-world variance
  across different hardware will differ, sometimes significantly, from these
  absolute numbers. The *ratios* (2.85x speedup) are more portable than the
  raw seconds.
