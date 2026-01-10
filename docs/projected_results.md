# InferBench — Projected Results After Framework v1.1 Fixes

> **STATUS: PROJECTED, NOT MEASURED.**
> Every number in this document is an *estimate*, derived from (a) the
> measured single-run results of the January 10, 2026 MeluXina session
> (see `benchmark_report.md`) and (b) reasoning from the architectural
> properties of the serving backends. No new benchmark has been executed.
> These projections define the *expected* outcome of re-running the
> improved pipeline and must be replaced by measured data before being
> cited as results. Cells marked ⊘ have no measured anchor at all.

## 1. Why this document exists

The January report has three methodological gaps: single-run measurements
(n = 1, no variance), a single load point (20 concurrent requests) instead
of a saturation curve, and no cross-backend comparison. Framework v1.1
closes the tooling gaps (repetition-aware client, concurrency sweep mode,
token-level metrics, corrected percentile statistics). Cluster access is
currently unavailable, so this document states — in advance and in
writing — what those runs are expected to show. Pre-registering expected
results is standard practice; presenting them as measurements is not.

## 2. Assumptions

| # | Assumption | Why it matters |
|---|-----------|----------------|
| A1 | Same hardware as January: 1× MeluXina GPU node, 4× A100-SXM4-40GB | All anchors were measured there |
| A2 | Ollama 0.13.x, 4-bit quantized models (Q4_0 / Q4_K_M) | Throughput anchors are quantization-specific |
| A3 | `OLLAMA_NUM_PARALLEL = 4` (Ollama's default parallel decode slots) | Directly caps the concurrency scaling of §4 |
| A4 | 100-token generation cap, short prompts (≤ 30 tokens) | Latency ≈ decode time; longer prompts shift TTFT up |
| A5 | Single-run January numbers are near the true means | Reasonable for GPU decode, which is low-variance, but unverified |

## 3. Projected single-stream throughput (n = 10 repetitions)

Measured single runs are used as the point estimate of the mean; the
projected standard deviation (±3–6 %) is typical run-to-run jitter for
steady-state GPU decoding (clock/thermal variation, scheduler noise).

| Model | Measured (n=1, Jan 2026) | **Projected mean ± σ (n=10)** |
|---|---|---|
| TinyLlama 1B | 480.0 tok/s | ~465–485 ± 15 tok/s |
| Phi-2 2.7B | 280.0 tok/s | ~270–285 ± 10 tok/s |
| CodeLlama 7B | 242.5 tok/s | ~235–248 ± 9 tok/s |
| Llama2 7B | 232.5 tok/s | ~225–238 ± 9 tok/s |
| Mistral 7B (Q4_K_M) | 171.4 tok/s | ~165–178 ± 7 tok/s |

Expected finding: the CodeLlama-vs-Llama2 gap (242.5 vs 232.5) may fall
*within* overlapping error bars, i.e. the repetition study may show it is
not statistically meaningful. That would itself be a valid, honest result.

## 4. Projected concurrency sweep — Ollama, Mistral 7B

Reasoning: Ollama decodes at most `NUM_PARALLEL` requests concurrently
(A3); additional requests queue. Throughput should therefore rise roughly
linearly up to C ≈ 4, then plateau, while p95 latency grows approximately
linearly with queue depth. The single measured anchor is 2.6 req/s at
C = 20 (longer "count to N" prompts, so the 100-token-cap sweep should
plateau somewhat higher).

| Concurrency C | Projected throughput (req/s) | Projected p95 latency |
|---|---|---|
| 1 | ~1.2–1.5 | ~0.8–1.0 s |
| 2 | ~2.2–2.8 | ~0.9–1.1 s |
| 4 | ~3.0–4.0 | ~1.1–1.5 s |
| 8 | ~3.0–4.2 (plateau) | ~2.0–2.8 s |
| 16 | ~3.0–4.2 | ~4–6 s |
| 32 | ~3.0–4.2 | ~8–12 s |

Expected finding: a clear saturation knee at C ≈ `NUM_PARALLEL`,
demonstrating that Ollama's static parallelism — not the A100 — is the
bottleneck. Failure mode to watch for: request timeouts at C ≥ 32.

## 5. Projected Ollama vs vLLM comparison — 7B model, same node ⊘

No measured anchor exists (vLLM was never benchmarked in January), so
these are order-of-magnitude expectations from vLLM's architecture:
continuous batching merges concurrent requests into shared GPU batches
and PagedAttention removes KV-cache fragmentation, so aggregate
throughput keeps scaling far beyond Ollama's 4-slot plateau.

| Metric @ C = 32, 100-token outputs | Ollama (projected) | vLLM (projected) ⊘ |
|---|---|---|
| Throughput | ~3–4 req/s | ~10–25 req/s |
| Aggregate decode throughput | ~400–700 tok/s | ~1500–3000 tok/s |
| p95 latency | ~8–12 s | ~2–5 s |

Expected headline (if confirmed): **~3–6× serving throughput from the
backend choice alone, on identical hardware** — the framework's central
demonstration that AI-Factory performance is a software-stack property,
not only a hardware property. The wide ranges reflect genuine
uncertainty (dtype FP16 vs AWQ, max batch size, scheduler settings);
this row in particular must not be quoted without measurement.

## 6. Validation checklist (to convert projections into results)

1. `inferbench server start --recipe ollama-inference`
2. `inferbench client run --recipe concurrency-sweep` — repeat with
   `--override pattern.repetitions` for n = 10 single-stream runs
3. Same sweep against `vllm-inference` (api_format: openai)
4. Replace every table above with measured values + generated
   `benchmark_results.json`; archive raw JSON under `results/`
5. Delete the "PROJECTED" banner only when every ⊘ cell is measured

*Document generated for planning purposes — v1.1, July 2026.*
