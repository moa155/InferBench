"""
Monitor Module for UBenchAI Framework.

Provides Prometheus and Grafana deployment for metrics collection.
"""

from ubenchai.monitors.manager import MonitorManager, get_monitor_manager

__all__ = [
    "MonitorManager",
    "get_monitor_manager",
]
