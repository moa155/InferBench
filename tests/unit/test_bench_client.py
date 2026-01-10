"""
Tests for the standalone benchmark client and the fixed statistics.

These tests exist because InferBench is a *benchmarking* framework:
if the statistics are wrong, every result the framework produces is
wrong, so percentile correctness is verified against known values.
"""

import json
from pathlib import Path

import pytest

from inferbench.analysis.analyzer import BenchmarkAnalyzer
from inferbench.clients import bench_client


class TestPercentile:
    """Percentile must use linear interpolation and never fall back to max."""

    def test_median_matches_statistics_median(self):
        # Even-length list: naive int-indexing picks the upper element;
        # linear interpolation must return the true midpoint (2.5).
        values = [1.0, 2.0, 3.0, 4.0]
        assert bench_client.percentile(values, 50) == pytest.approx(2.5)
        assert BenchmarkAnalyzer.percentile(values, 50) == pytest.approx(2.5)

    def test_p95_small_sample_is_not_max(self):
        # Old behaviour returned max(values)=100 for n < 20, silently
        # overstating the tail. Interpolated p95 of 1..10 is 9.55.
        values = list(map(float, range(1, 10))) + [100.0]
        p95 = bench_client.percentile(values, 95)
        assert p95 < 100.0
        assert p95 == pytest.approx(9 + 0.55 * 91, rel=1e-6)  # 59.05

    def test_known_percentiles(self):
        values = list(map(float, range(1, 101)))  # 1..100
        assert bench_client.percentile(values, 50) == pytest.approx(50.5)
        assert bench_client.percentile(values, 95) == pytest.approx(95.05)
        assert bench_client.percentile(values, 99) == pytest.approx(99.01)

    def test_single_value(self):
        assert bench_client.percentile([7.0], 99) == 7.0

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            bench_client.percentile([], 50)


class TestRequestBuilding:
    def test_ollama_body_uses_num_predict(self):
        cfg = {"api_format": "ollama", "model": "mistral", "max_tokens": 64}
        body = bench_client.build_body(cfg, "hi")
        assert body["model"] == "mistral"
        assert body["stream"] is False
        assert body["options"]["num_predict"] == 64

    def test_openai_body_uses_max_tokens(self):
        cfg = {"api_format": "openai", "model": "m", "max_tokens": 64}
        body = bench_client.build_body(cfg, "hi")
        assert body["max_tokens"] == 64
        assert "options" not in body


class TestTokenMetrics:
    def test_ollama_decode_tps_from_nanoseconds(self):
        # Ollama reports durations in ns: 100 tokens in 0.5 s = 200 tok/s.
        payload = {
            "eval_count": 100,
            "eval_duration": 500_000_000,
            "prompt_eval_duration": 200_000_000,
            "load_duration": 100_000_000,
        }
        m = bench_client.parse_token_metrics({"api_format": "ollama"}, payload)
        assert m["decode_tokens_per_second"] == pytest.approx(200.0)
        assert m["ttft_s"] == pytest.approx(0.3)

    def test_missing_fields_yield_empty(self):
        assert bench_client.parse_token_metrics({"api_format": "ollama"}, {}) == {}


class TestStatsAssembly:
    def test_build_stats_aggregates_successes_only(self):
        cfg = {"benchmark_name": "t", "target_endpoint": "http://x"}
        results = [
            {"success": True, "latency_s": 1.0, "decode_tokens_per_second": 100.0},
            {"success": True, "latency_s": 3.0, "decode_tokens_per_second": 300.0},
            {"success": False, "latency_s": 9.0},
        ]
        stats = bench_client.build_stats(cfg, results, extra={"mode": "rate"})
        assert stats["summary"] == {
            "total_requests": 3, "successes": 2, "failures": 1
        }
        assert stats["latency_s"]["mean"] == pytest.approx(2.0)
        assert stats["decode_tokens_per_second"]["max"] == pytest.approx(300.0)


class TestMainEntry:
    def test_missing_required_keys_exit_code(self, tmp_path: Path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"target_endpoint": ""}))
        assert bench_client.main(["bench_client.py", str(cfg)]) == 2

    def test_usage_without_config(self):
        assert bench_client.main(["bench_client.py"]) == 2
