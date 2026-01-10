"""
Web Interface Module for UBenchAI Framework.

Provides a Flask-based dashboard for monitoring and managing benchmarks.
"""

from ubenchai.interface.web.app import create_app, run_server

__all__ = [
    "create_app",
    "run_server",
]
