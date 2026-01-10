"""
Tests for the Web Interface module.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from ubenchai.interface.web.app import create_app
from ubenchai.core.models import ServiceStatus, RunStatus


class TestWebApp:
    """Tests for Flask web application."""
    
    @pytest.fixture
    def app(self):
        """Create test Flask app."""
        with patch('ubenchai.interface.web.app.get_server_manager'), \
             patch('ubenchai.interface.web.app.get_client_manager'), \
             patch('ubenchai.interface.web.app.get_monitor_manager'), \
             patch('ubenchai.interface.web.app.get_log_manager'):
            app = create_app({"TESTING": True})
            return app
    
    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return app.test_client()
    
    def test_health_check(self, client):
        """Should return healthy status."""
        response = client.get('/health')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'healthy'
        assert 'timestamp' in data
        assert data['version'] == '0.1.0'
    
    def test_index_page(self, client):
        """Should return index page."""
        response = client.get('/')
        
        assert response.status_code == 200
        assert b'UBenchAI' in response.data
    
    def test_services_page(self, client):
        """Should return services page."""
        response = client.get('/services')
        
        assert response.status_code == 200
        assert b'Services' in response.data
    
    def test_benchmarks_page(self, client):
        """Should return benchmarks page."""
        response = client.get('/benchmarks')
        
        assert response.status_code == 200
        assert b'Benchmarks' in response.data
    
    def test_monitoring_page(self, client):
        """Should return monitoring page."""
        response = client.get('/monitoring')
        
        assert response.status_code == 200
        assert b'Monitoring' in response.data
    
    def test_logs_page(self, client):
        """Should return logs page."""
        response = client.get('/logs')
        
        assert response.status_code == 200
        assert b'Logs' in response.data


class TestServicesAPI:
    """Tests for Services API endpoints."""
    
    @pytest.fixture
    def mock_service(self):
        """Create mock service."""
        service = MagicMock()
        service.id = "svc-001"
        service.recipe_name = "vllm-inference"
        service.status = ServiceStatus.RUNNING
        service.node = "mel2091"
        service.slurm_job_id = "12345678"
        service.created_at = datetime.now()
        service.started_at = datetime.now()
        service.endpoints = {"api": "http://mel2091:8000"}
        service.error_message = None
        return service
    
    @pytest.fixture
    def app_with_services(self, mock_service):
        """Create app with mocked service manager."""
        mock_manager = MagicMock()
        mock_manager.list_services.return_value = [mock_service]
        mock_manager.get_service_status.return_value = mock_service
        mock_manager.list_available_recipes.return_value = ["vllm-inference"]
        
        with patch('ubenchai.interface.web.app.get_server_manager', return_value=mock_manager), \
             patch('ubenchai.interface.web.app.get_client_manager'), \
             patch('ubenchai.interface.web.app.get_monitor_manager'), \
             patch('ubenchai.interface.web.app.get_log_manager'):
            app = create_app({"TESTING": True})
            return app
    
    def test_list_services(self, app_with_services):
        """Should list services."""
        client = app_with_services.test_client()
        response = client.get('/api/services')
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'services' in data
        assert data['total'] == 1
        assert data['services'][0]['recipe_name'] == 'vllm-inference'
    
    def test_get_service(self, app_with_services):
        """Should get service details."""
        client = app_with_services.test_client()
        response = client.get('/api/services/svc-001')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == 'svc-001'
        assert data['status'] == 'running'


class TestBenchmarksAPI:
    """Tests for Benchmarks API endpoints."""
    
    @pytest.fixture
    def mock_run(self):
        """Create mock benchmark run."""
        run = MagicMock()
        run.id = "run-001"
        run.recipe_name = "llm-stress-test"
        run.status = RunStatus.COMPLETED
        run.slurm_job_id = "87654321"
        run.target_service_id = None
        run.created_at = datetime.now()
        run.completed_at = datetime.now()
        run.results_path = "/path/to/results"
        run.error_message = None
        return run
    
    @pytest.fixture
    def app_with_benchmarks(self, mock_run):
        """Create app with mocked client manager."""
        mock_manager = MagicMock()
        mock_manager.list_runs.return_value = [mock_run]
        mock_manager.get_run_status.return_value = mock_run
        mock_manager.get_run_results.return_value = {
            "summary": {"total_requests": 100, "success_rate": 95.0}
        }
        mock_manager.list_available_recipes.return_value = ["llm-stress-test"]
        
        with patch('ubenchai.interface.web.app.get_server_manager'), \
             patch('ubenchai.interface.web.app.get_client_manager', return_value=mock_manager), \
             patch('ubenchai.interface.web.app.get_monitor_manager'), \
             patch('ubenchai.interface.web.app.get_log_manager'):
            app = create_app({"TESTING": True})
            return app
    
    def test_list_benchmarks(self, app_with_benchmarks):
        """Should list benchmark runs."""
        client = app_with_benchmarks.test_client()
        response = client.get('/api/benchmarks')
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'runs' in data
        assert data['total'] == 1
    
    def test_get_benchmark_results(self, app_with_benchmarks):
        """Should get benchmark results."""
        client = app_with_benchmarks.test_client()
        response = client.get('/api/benchmarks/run-001/results')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['summary']['total_requests'] == 100


class TestDashboardAPI:
    """Tests for Dashboard API endpoints."""
    
    @pytest.fixture
    def app_with_stats(self):
        """Create app with mocked managers for stats."""
        mock_server = MagicMock()
        mock_server.list_services.return_value = []
        
        mock_client = MagicMock()
        mock_client.list_runs.return_value = []
        
        mock_monitor = MagicMock()
        mock_monitor.list_monitors.return_value = []
        
        with patch('ubenchai.interface.web.app.get_server_manager', return_value=mock_server), \
             patch('ubenchai.interface.web.app.get_client_manager', return_value=mock_client), \
             patch('ubenchai.interface.web.app.get_monitor_manager', return_value=mock_monitor), \
             patch('ubenchai.interface.web.app.get_log_manager'):
            app = create_app({"TESTING": True})
            return app
    
    def test_dashboard_stats(self, app_with_stats):
        """Should return dashboard statistics."""
        client = app_with_stats.test_client()
        response = client.get('/api/dashboard/stats')
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'services' in data
        assert 'benchmarks' in data
        assert 'monitors' in data
        assert 'timestamp' in data
