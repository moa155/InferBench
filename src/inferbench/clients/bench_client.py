#!/usr/bin/env python3
"""
InferBench standalone benchmark client.

This file is copied verbatim to the client work directory on the compute
node and executed there. It deliberately depends ONLY on the Python
standard library, because the inferbench package (and third-party
libraries) may not be installed inside the job environment.

All parameters come from a JSON config file passed as argv[1]. No source
code is ever generated or templated: this removes the injection surface
and makes the client unit-testable.

Config schema (all keys optional unless stated):
{
  "benchmark_name":    str,   # label written into results
  "target_endpoint":   str,   # REQUIRED, e.g. "http://mel2044:11434"
  "endpoint_path":     str,   # default "/api/generate" (Ollama)
  "api_format":        str,   # "ollama" | "openai" | "raw" (default "ollama")
  "model":             str,   # model name sent in the request body
  "prompts":           [str], # prompt pool, one is chosen per request
  "max_tokens":        int,   # generation cap per request (default 100)
  "temperature":       float, # default 0.7
  "mode":              str,   # "rate" (open-loop) | "sweep" (concurrency sweep)
  "rate":              float, # rate mode: target requests/second
  "duration":          int,   # rate mode: seconds to run
  "concurrency_levels":[int], # sweep mode: e.g. [1, 2, 4, 8, 16, 32]
  "requests_per_level":int,   # sweep mode: requests at each level (default 20)
  "warmup_requests":   int,   # excluded from statistics (default 2)
  "results_dir":       str    # REQUIRED, where JSON results are written
}

Metrics collected per request:
- latency_s:        end-to-end wall time (perf_counter)
- For api_format == "ollama", parsed from the response body:
  - eval_count / eval_duration  -> decode_tokens_per_second
    (Ollama reports eval_duration in nanoseconds; this is generation-only
    throughput, EXCLUDING prompt processing)
  - prompt_eval_duration_s      -> prompt processing time
  - ttft_s (approx)             -> load + prompt eval time, i.e. time
    before the first output token according to the server's own timers
"""

import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

NS = 1e9  # Ollama durations are reported in nanoseconds


# --------------------------------------------------------------------------
# Statistics helpers
# --------------------------------------------------------------------------

def percentile(values: list, p: float) -> float:
    """
    Percentile with linear interpolation between closest ranks
    (same method as numpy's default "linear").

    Why interpolation: naive indexing like sorted[int(n*0.95)] is biased
    for small samples and inconsistent with statistics.median; linear
    interpolation is the standard, reproducible definition.
    """
    if not values:
        raise ValueError("percentile() of empty list")
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return float(s[lo] * (1.0 - frac) + s[hi] * frac)


def summarize(values: list) -> dict:
    """Full descriptive statistics for a list of samples."""
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "std_dev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


# --------------------------------------------------------------------------
# Request construction / parsing
# --------------------------------------------------------------------------

def build_body(cfg: dict, prompt: str) -> dict:
    """Build the request body for the configured API format."""
    fmt = cfg.get("api_format", "ollama")
    model = cfg.get("model") or os.environ.get("MODEL_NAME", "tinyllama")
    if fmt == "openai":
        # OpenAI-compatible /v1/completions (vLLM exposes this)
        return {
            "model": model,
            "prompt": prompt,
            "max_tokens": cfg.get("max_tokens", 100),
            "temperature": cfg.get("temperature", 0.7),
        }
    # Ollama native /api/generate. num_predict is Ollama's max-tokens knob.
    return {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": cfg.get("max_tokens", 100),
            "temperature": cfg.get("temperature", 0.7),
        },
    }


def parse_token_metrics(cfg: dict, payload: dict) -> dict:
    """
    Extract token-level metrics from a successful response body.

    Returns {} when the backend does not expose them (e.g. raw HTTP),
    so callers can merge unconditionally.
    """
    fmt = cfg.get("api_format", "ollama")
    out: dict = {}
    if fmt == "ollama":
        eval_count = payload.get("eval_count")
        eval_duration = payload.get("eval_duration")  # ns
        if eval_count and eval_duration:
            out["tokens_generated"] = eval_count
            out["decode_tokens_per_second"] = eval_count / (eval_duration / NS)
        prompt_eval = payload.get("prompt_eval_duration")  # ns
        load_dur = payload.get("load_duration")  # ns
        if prompt_eval is not None:
            out["prompt_eval_duration_s"] = prompt_eval / NS
            # Server-side time before the first generated token:
            # model load (if any) + prompt processing.
            out["ttft_s"] = ((load_dur or 0) + prompt_eval) / NS
    elif fmt == "openai":
        usage = payload.get("usage") or {}
        if usage.get("completion_tokens"):
            out["tokens_generated"] = usage["completion_tokens"]
    return out


def make_request(cfg: dict, prompt: str) -> dict:
    """Issue one request and return a result record (never raises)."""
    url = cfg["target_endpoint"].rstrip("/") + cfg.get("endpoint_path", "/api/generate")
    method = cfg.get("method", "POST").upper()
    body = json.dumps(build_body(cfg, prompt)).encode() if method == "POST" else None

    start = time.perf_counter()
    try:
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=cfg.get("request_timeout", 120)) as resp:
            raw = resp.read()
            latency = time.perf_counter() - start
            record = {
                "success": resp.status == 200,
                "status_code": resp.status,
                "latency_s": latency,
                "error": None,
            }
            try:
                record.update(parse_token_metrics(cfg, json.loads(raw)))
            except (ValueError, KeyError):
                pass  # non-JSON body: keep e2e latency only
            return record
    except Exception as e:  # noqa: BLE001 - a bench client must survive anything
        return {
            "success": False,
            "status_code": 0,
            "latency_s": time.perf_counter() - start,
            "error": str(e),
        }


# --------------------------------------------------------------------------
# Benchmark modes
# --------------------------------------------------------------------------

def run_warmup(cfg: dict) -> None:
    """
    Fire-and-discard requests before measuring.

    Why: the first requests pay one-off costs (model load into VRAM,
    CUDA graph capture, cache population) that would contaminate the
    steady-state statistics.
    """
    n = cfg.get("warmup_requests", 2)
    prompts = cfg.get("prompts") or ["Hello, how are you?"]
    for _ in range(n):
        make_request(cfg, random.choice(prompts))


def run_rate_mode(cfg: dict) -> tuple[list, dict]:
    """
    Open-loop load: send requests at a fixed target rate for a fixed
    duration, regardless of whether previous requests completed.
    This models independent users arriving over time.
    """
    rate = float(cfg.get("rate", 10))
    duration = int(cfg.get("duration", 60))
    prompts = cfg.get("prompts") or ["Hello, how are you?"]
    interval = 1.0 / rate

    results = []
    start = time.perf_counter()
    count = 0
    while time.perf_counter() - start < duration:
        results.append(make_request(cfg, random.choice(prompts)))
        count += 1
        if count % 10 == 0:
            elapsed = time.perf_counter() - start
            print(f"progress: {count} req, {elapsed:.1f}s, {count / elapsed:.2f} req/s")
        time.sleep(interval)

    total = time.perf_counter() - start
    stats = build_stats(cfg, results, extra={
        "mode": "rate",
        "target_rate_rps": rate,
        "duration_s": duration,
        "achieved_rate_rps": len(results) / total if total > 0 else 0.0,
    })
    return results, stats


def run_sweep_mode(cfg: dict) -> tuple[list, dict]:
    """
    Closed-loop concurrency sweep: for each concurrency level C, keep
    exactly C requests in flight until N requests complete, then record
    throughput and latency percentiles for that level.

    Why this is THE core inference benchmark: plotting throughput and
    tail latency against concurrency reveals where the server saturates
    and how latency degrades under load — a single point cannot.
    """
    levels = cfg.get("concurrency_levels") or [1, 2, 4, 8, 16, 32]
    per_level = int(cfg.get("requests_per_level", 20))
    prompts = cfg.get("prompts") or ["Hello, how are you?"]

    all_raw = []
    level_stats = []
    for c in levels:
        print(f"--- concurrency level {c}: {per_level} requests ---")
        level_results = []
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=c) as pool:
            futures = [
                pool.submit(make_request, cfg, random.choice(prompts))
                for _ in range(per_level)
            ]
            for fut in as_completed(futures):
                level_results.append(fut.result())
        wall = time.perf_counter() - t0

        ok = [r for r in level_results if r["success"]]
        lat = [r["latency_s"] for r in ok]
        tps = [r["decode_tokens_per_second"] for r in ok
               if r.get("decode_tokens_per_second")]
        toks = sum(r.get("tokens_generated", 0) for r in ok)
        level_stats.append({
            "concurrency": c,
            "requests": per_level,
            "successes": len(ok),
            "failures": per_level - len(ok),
            "wall_time_s": wall,
            "throughput_rps": len(ok) / wall if wall > 0 else 0.0,
            "aggregate_tokens_per_second": toks / wall if wall > 0 else 0.0,
            "latency_s": summarize(lat),
            "per_request_decode_tps": summarize(tps),
        })
        for r in level_results:
            r["concurrency"] = c
        all_raw.extend(level_results)

    stats = build_stats(cfg, all_raw, extra={
        "mode": "sweep",
        "concurrency_levels": levels,
        "requests_per_level": per_level,
        "levels": level_stats,
    })
    return all_raw, stats


def build_stats(cfg: dict, results: list, extra: dict) -> dict:
    """Aggregate raw records into the summary written to disk."""
    ok = [r for r in results if r["success"]]
    lat = [r["latency_s"] for r in ok]
    tps = [r["decode_tokens_per_second"] for r in ok
           if r.get("decode_tokens_per_second")]
    ttft = [r["ttft_s"] for r in ok if r.get("ttft_s") is not None]
    stats = {
        "benchmark": cfg.get("benchmark_name", "unnamed"),
        "timestamp": datetime.now().isoformat(),
        "target": cfg.get("target_endpoint"),
        "model": cfg.get("model"),
        "api_format": cfg.get("api_format", "ollama"),
        "summary": {
            "total_requests": len(results),
            "successes": len(ok),
            "failures": len(results) - len(ok),
        },
        "latency_s": summarize(lat),
        "decode_tokens_per_second": summarize(tps),
        "ttft_s": summarize(ttft),
    }
    stats.update(extra)
    return stats


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main(argv: list) -> int:
    if len(argv) < 2:
        print("usage: bench_client.py <config.json>", file=sys.stderr)
        return 2
    cfg = json.loads(Path(argv[1]).read_text())

    for required in ("target_endpoint", "results_dir"):
        if not cfg.get(required):
            print(f"config error: '{required}' is required", file=sys.stderr)
            return 2

    print("=" * 60)
    print("InferBench Benchmark Client")
    print("=" * 60)
    print(f"Target: {cfg['target_endpoint']}  Mode: {cfg.get('mode', 'rate')}")

    run_warmup(cfg)
    if cfg.get("mode", "rate") == "sweep":
        raw, stats = run_sweep_mode(cfg)
    else:
        raw, stats = run_rate_mode(cfg)

    results_dir = Path(cfg["results_dir"])
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "benchmark_results.json").write_text(json.dumps(stats, indent=2))
    (results_dir / "raw_results.json").write_text(json.dumps(raw, indent=2))
    print(f"Results saved to: {results_dir / 'benchmark_results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
