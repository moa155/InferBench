"""Benchmark result analyzer with statistical analysis."""

import json
import statistics
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

@dataclass
class AnalysisResult:
    """Statistical analysis result."""
    metric: str
    count: int
    mean: float
    median: float
    std_dev: float
    min_val: float
    max_val: float
    p50: float
    p95: float
    p99: float

class BenchmarkAnalyzer:
    """Analyzes benchmark results and generates statistics."""
    
    def __init__(self, data_path: Optional[Path] = None):
        self.data_path = data_path
        self.data = []
    
    def load_data(self, path: Path) -> None:
        """Load benchmark data from JSON file."""
        with open(path) as f:
            self.data = json.load(f)
    
    @staticmethod
    def percentile(values: list[float], p: float) -> float:
        """
        Percentile with linear interpolation between closest ranks
        (numpy's default "linear" method).

        Why this replaces the previous index-based lookup:
        - sorted[int(n*0.95)] has an off-by-one bias and disagrees with
          statistics.median for even n;
        - the old code silently returned the MAXIMUM for p95 when n < 20
          and for p99 when n < 100, overstating tail latency without
          telling the caller. With interpolation the estimate is defined
          for any n >= 1 (for tiny samples it is still a rough estimate,
          but a documented, reproducible one).
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

    def analyze_metric(self, values: list[float], metric_name: str) -> AnalysisResult:
        """Perform statistical analysis on a metric."""
        if not values:
            raise ValueError("No values to analyze")
        
        n = len(values)
        
        return AnalysisResult(
            metric=metric_name,
            count=n,
            mean=statistics.mean(values),
            median=statistics.median(values),
            std_dev=statistics.stdev(values) if n > 1 else 0,
            min_val=min(values),
            max_val=max(values),
            p50=self.percentile(values, 50),
            p95=self.percentile(values, 95),
            p99=self.percentile(values, 99),
        )
    
    def analyze_throughput(self, results: list[dict]) -> AnalysisResult:
        """Analyze throughput metrics."""
        values = [r.get("tokens_per_second", 0) for r in results if r.get("tokens_per_second")]
        return self.analyze_metric(values, "throughput_tokens_per_sec")
    
    def analyze_latency(self, results: list[dict]) -> AnalysisResult:
        """Analyze latency metrics."""
        values = [r.get("latency_ms", 0) for r in results if r.get("latency_ms")]
        return self.analyze_metric(values, "latency_ms")
    
    def generate_summary(self, results: list[dict]) -> dict:
        """Generate a complete analysis summary."""
        summary = {
            "total_runs": len(results),
            "successful_runs": len([r for r in results if r.get("success", True)]),
            "failed_runs": len([r for r in results if not r.get("success", True)]),
        }
        
        # Analyze by model
        models = {}
        for r in results:
            model = r.get("model", "unknown")
            if model not in models:
                models[model] = []
            models[model].append(r)
        
        summary["models"] = {}
        for model, model_results in models.items():
            tps_values = [r.get("tokens_per_second", 0) for r in model_results if r.get("tokens_per_second")]
            if tps_values:
                summary["models"][model] = {
                    "runs": len(model_results),
                    "avg_throughput": statistics.mean(tps_values),
                    "max_throughput": max(tps_values),
                    "min_throughput": min(tps_values),
                }
        
        return summary
    
    def to_json(self, summary: dict) -> str:
        """Convert summary to JSON string."""
        return json.dumps(summary, indent=2)
