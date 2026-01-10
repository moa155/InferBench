"""
Client Manager for InferBench Framework.

Handles benchmark client execution, workload management,
and results collection on SLURM-managed HPC clusters.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from inferbench.core.config import get_config
from inferbench.core.exceptions import (
    ClientRunError,
    ClientNotFoundError,
    RecipeNotFoundError,
    ServiceNotFoundError,
)
from inferbench.core.models import (
    ClientRun,
    RunStatus,
    ClientRecipe,
    RecipeType,
    ServiceInstance,
)
from inferbench.core.recipe_loader import RecipeLoader, get_recipe_loader
from inferbench.core.registry import RunRegistry, get_run_registry, get_service_registry
from inferbench.core.slurm import SlurmOrchestrator, get_slurm_orchestrator
from inferbench.core.apptainer import ApptainerRuntime, get_apptainer_runtime
from inferbench.utils.logging import get_logger

logger = get_logger(__name__)


class ClientManager:
    """
    Manages benchmark client execution on HPC clusters.
    
    Coordinates workload submission, monitoring, and results collection.
    """
    
    def __init__(
        self,
        recipe_loader: Optional[RecipeLoader] = None,
        registry: Optional[RunRegistry] = None,
        orchestrator: Optional[SlurmOrchestrator] = None,
        runtime: Optional[ApptainerRuntime] = None,
    ):
        """
        Initialize the client manager.
        
        Args:
            recipe_loader: Recipe loader instance
            registry: Run registry instance
            orchestrator: SLURM orchestrator instance
            runtime: Apptainer runtime instance
        """
        self.config = get_config()
        self.recipe_loader = recipe_loader or get_recipe_loader()
        self.registry = registry or get_run_registry()
        self.service_registry = get_service_registry()
        self.orchestrator = orchestrator or get_slurm_orchestrator()
        self.runtime = runtime or get_apptainer_runtime()
        
        # Ensure required directories exist
        self._setup_directories()
        
        logger.info("ClientManager initialized")
    
    def _setup_directories(self) -> None:
        """Create required directories for client operations."""
        dirs = [
            self.config.logs_dir / "clients",
            self.config.results_dir / "clients",
            Path("/tmp/inferbench/clients"),
        ]
        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    def _get_work_dir(self, run_id: str) -> Path:
        """Get the working directory for a client run."""
        work_dir = self.config.logs_dir / "clients" / run_id
        work_dir.mkdir(parents=True, exist_ok=True)
        return work_dir
    
    def _get_results_dir(self, run_id: str) -> Path:
        """Get the results directory for a client run."""
        results_dir = self.config.results_dir / "clients" / run_id
        results_dir.mkdir(parents=True, exist_ok=True)
        return results_dir
    
    def _resolve_target_endpoint(
        self, 
        recipe: ClientRecipe, 
        target_service_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Resolve the target service endpoint.
        
        Args:
            recipe: Client recipe with target configuration
            target_service_id: Optional specific service ID to target
            
        Returns:
            Target endpoint URL or None
        """
        # If target looks like a URL, use it directly
        if target_service_id and target_service_id.startswith(("http://", "https://")):
            logger.info(f"Using direct target URL: {target_service_id}")
            return target_service_id

        # If specific service ID provided, look it up
        if target_service_id:
            try:
                service = self.service_registry.get(target_service_id)
                endpoint = service.get_endpoint("api")
                if endpoint:
                    logger.info(f"Resolved target endpoint from service {target_service_id}: {endpoint}")
                    return endpoint
            except ServiceNotFoundError:
                logger.warning(f"Target service {target_service_id} not found")
        
        # Check recipe target configuration
        target_config = recipe.target
        
        # Direct URL specified
        if "url" in target_config:
            return target_config["url"]
        
        # Endpoint file specified (written by server)
        if "endpoint_file" in target_config:
            endpoint_file = Path(target_config["endpoint_file"])
            if endpoint_file.exists():
                try:
                    content = endpoint_file.read_text()
                    for line in content.split("\n"):
                        if line.startswith("ENDPOINT="):
                            return line.split("=", 1)[1].strip()
                except Exception as e:
                    logger.warning(f"Failed to read endpoint file: {e}")
        
        return None
    
    def _build_client_command(
        self,
        recipe: ClientRecipe,
        target_endpoint: Optional[str],
        results_dir: Path,
        work_dir: Path,
    ) -> str:
        """
        Prepare the client working directory and return the shell command
        to place in the SLURM batch script.

        Three cases:
        - container recipe: the Apptainer exec script is a *bash* script,
          so it is written to disk and invoked with bash (previously it
          was invoked with python3, which could never work);
        - HTTP workload: the static bench_client.py is copied next to a
          generated JSON config (no source-code templating);
        - fallback: the recipe's raw command.
        """
        # If recipe has a container, use it
        if recipe.container:
            container_cmd = self.runtime.generate_exec_script(
                container_spec=recipe.container,
                resources=recipe.resources,
                command=recipe.command or "echo 'No command specified'",
                environment=recipe.environment,
            )
            script_file = work_dir / "container_exec.sh"
            script_file.write_text(container_cmd)
            script_file.chmod(0o755)
            return f"bash {script_file}"

        workload = recipe.workload
        workload_type = workload.get("type", "simple")

        if workload_type in ["open-loop", "closed-loop", "stress-test", "sweep"]:
            return self._prepare_http_benchmark(
                recipe, target_endpoint, results_dir, work_dir
            )

        # Default: just run the command if specified
        return recipe.command or "echo 'No benchmark command specified'"

    def _build_benchmark_config(
        self,
        recipe: ClientRecipe,
        target_endpoint: Optional[str],
        results_dir: Path,
    ) -> dict:
        """
        Translate a client recipe into the bench_client.py JSON config.

        Kept separate from file I/O so tests can assert on the mapping
        without touching the filesystem.
        """
        workload = recipe.workload
        pattern = workload.get("pattern", {})
        request_config = workload.get("request", {})
        dataset = workload.get("dataset", {})

        mode = "sweep" if workload.get("type") == "sweep" else "rate"

        config = {
            "benchmark_name": recipe.name,
            "target_endpoint": target_endpoint or "http://localhost:8000",
            "endpoint_path": request_config.get("endpoint", "/api/generate"),
            "method": request_config.get("method", "POST"),
            "api_format": request_config.get("api_format", "ollama"),
            "model": request_config.get("model"),
            "max_tokens": request_config.get("max_tokens", 100),
            "temperature": request_config.get("temperature", 0.7),
            "prompts": dataset.get("prompts", ["Hello, how are you?"]),
            "warmup_requests": pattern.get("warmup_requests", 2),
            "mode": mode,
            "rate": pattern.get("rate", 10),
            "duration": pattern.get("duration", 60),
            "concurrency_levels": pattern.get(
                "concurrency_levels", [1, 2, 4, 8, 16, 32]
            ),
            "requests_per_level": pattern.get("requests_per_level", 20),
            "results_dir": str(results_dir),
        }
        return config

    def _prepare_http_benchmark(
        self,
        recipe: ClientRecipe,
        target_endpoint: Optional[str],
        results_dir: Path,
        work_dir: Path,
    ) -> str:
        """
        Copy the static benchmark client and write its JSON config into
        the work directory; return the command that runs it.
        """
        import shutil

        source = Path(__file__).parent / "bench_client.py"
        script_file = work_dir / "bench_client.py"
        shutil.copyfile(source, script_file)

        config = self._build_benchmark_config(recipe, target_endpoint, results_dir)
        config_file = work_dir / "client_config.json"
        config_file.write_text(json.dumps(config, indent=2))

        return f"python3 {script_file} {config_file}"
    
    def run_client(
        self,
        recipe_name: str,
        target_service_id: Optional[str] = None,
        config_overrides: Optional[dict] = None,
        wait_for_completion: bool = False,
        timeout: int = 3600,
    ) -> ClientRun:
        """
        Run a benchmark client from a recipe.
        
        Args:
            recipe_name: Name of the client recipe
            target_service_id: Optional service ID to benchmark
            config_overrides: Optional configuration overrides
            wait_for_completion: Whether to wait for completion
            timeout: Timeout in seconds
            
        Returns:
            ClientRun object
            
        Raises:
            RecipeNotFoundError: If recipe doesn't exist
            ClientRunError: If client fails to start
        """
        logger.info(f"Starting client with recipe: {recipe_name}")
        
        # Load recipe
        try:
            recipe = self.recipe_loader.load_client(recipe_name)
        except RecipeNotFoundError:
            raise
        except Exception as e:
            raise ClientRunError(recipe_name, f"Failed to load recipe: {e}")
        
        # Apply overrides
        if config_overrides:
            recipe = self._apply_overrides(recipe, config_overrides)
        
        # Create client run instance
        run = ClientRun(
            recipe_name=recipe_name,
            recipe=recipe,
            status=RunStatus.SUBMITTED,
            target_service_id=target_service_id,
        )
        
        # Register the run
        self.registry.register(run)
        
        try:
            # Get working directories
            work_dir = self._get_work_dir(run.id)
            results_dir = self._get_results_dir(run.id)
            
            # Resolve target endpoint
            target_endpoint = self._resolve_target_endpoint(recipe, target_service_id)
            
            # Build client command
            # Prepares work_dir (client script + JSON config, or container
            # exec script) and returns the shell command to run it. The
            # previous implementation wrote whatever came back — including
            # bash container scripts — into a .py file and ran it with
            # python3, which broke the container path.
            client_command = self._build_client_command(
                recipe, target_endpoint, results_dir, work_dir
            )
            
            # Generate batch script
            batch_script = self.orchestrator.generate_batch_script(
                job_name=f"inferbench-client-{recipe_name}-{run.id}",
                command=client_command,
                resources=recipe.resources,
                environment=recipe.environment,
                output_dir=work_dir,
            )
            
            # Save batch script
            batch_file = work_dir / "job.sh"
            batch_file.write_text(batch_script)
            
            # Submit job
            self.registry.update_status(run.id, RunStatus.QUEUED)
            job_id = self.orchestrator.submit_job(
                script_content=batch_script,
                script_name=f"client_{run.id}.sh",
                work_dir=work_dir,
            )
            
            # Update run with job ID
            run.slurm_job_id = job_id
            run.results_path = str(results_dir)
            self.registry.register(run)
            
            logger.info(f"Client run {run.id} submitted as SLURM job {job_id}")
            
            # Wait for completion if requested
            if wait_for_completion:
                self._wait_for_completion(run, timeout)
            
            return run
            
        except Exception as e:
            self.registry.update_status(run.id, RunStatus.FAILED, str(e))
            raise ClientRunError(recipe_name, str(e))
    
    def _apply_overrides(self, recipe: ClientRecipe, overrides: dict) -> ClientRecipe:
        """Apply configuration overrides to a recipe."""
        recipe_dict = recipe.model_dump()
        
        for key, value in overrides.items():
            if key in recipe_dict:
                if isinstance(recipe_dict[key], dict) and isinstance(value, dict):
                    recipe_dict[key].update(value)
                else:
                    recipe_dict[key] = value
        
        return ClientRecipe(**recipe_dict)
    
    def _wait_for_completion(self, run: ClientRun, timeout: int) -> bool:
        """Wait for a client run to complete."""
        logger.info(f"Waiting for run {run.id} to complete (timeout: {timeout}s)")
        
        start_time = time.time()
        check_interval = 10
        
        while time.time() - start_time < timeout:
            # Check SLURM job status
            slurm_status = self.orchestrator.get_job_status(run.slurm_job_id)
            
            from inferbench.core.models import ServiceStatus
            
            if slurm_status == ServiceStatus.STOPPED:
                # Job completed - check if results exist
                results_file = Path(run.results_path) / "benchmark_results.json"
                if results_file.exists():
                    self.registry.update_status(run.id, RunStatus.COMPLETED)
                    run.status = RunStatus.COMPLETED
                    logger.info(f"Run {run.id} completed successfully")
                    return True
                else:
                    self.registry.update_status(run.id, RunStatus.FAILED, "No results generated")
                    return False
            
            elif slurm_status == ServiceStatus.ERROR:
                self.registry.update_status(run.id, RunStatus.FAILED, "SLURM job failed")
                return False
            
            elif slurm_status == ServiceStatus.RUNNING:
                self.registry.update_status(run.id, RunStatus.RUNNING)
                run.status = RunStatus.RUNNING
            
            time.sleep(check_interval)
        
        # Timeout
        self.registry.update_status(run.id, RunStatus.FAILED, "Timeout waiting for completion")
        return False
    
    def stop_run(self, run_id: str) -> bool:
        """
        Stop a running client.
        
        Args:
            run_id: Run ID to stop
            
        Returns:
            True if stopped successfully
        """
        logger.info(f"Stopping run: {run_id}")
        
        try:
            run = self.registry.get(run_id)
        except ClientNotFoundError:
            raise
        
        if not run.is_active():
            logger.warning(f"Run {run_id} is not active")
            return True
        
        # Cancel SLURM job
        if run.slurm_job_id:
            self.orchestrator.cancel_job(run.slurm_job_id)
        
        self.registry.update_status(run.id, RunStatus.CANCELED)
        logger.info(f"Run {run_id} canceled")
        return True
    
    def get_run_status(self, run_id: str) -> ClientRun:
        """Get the status of a client run."""
        run = self.registry.get(run_id)
        
        # Update from SLURM if active
        if run.is_active() and run.slurm_job_id:
            from inferbench.core.models import ServiceStatus
            slurm_status = self.orchestrator.get_job_status(run.slurm_job_id)
            
            if slurm_status == ServiceStatus.RUNNING:
                self.registry.update_status(run.id, RunStatus.RUNNING)
                run.status = RunStatus.RUNNING
            elif slurm_status == ServiceStatus.STOPPED:
                # Check results
                if run.results_path:
                    results_file = Path(run.results_path) / "benchmark_results.json"
                    if results_file.exists():
                        self.registry.update_status(run.id, RunStatus.COMPLETED)
                        run.status = RunStatus.COMPLETED
                    else:
                        self.registry.update_status(run.id, RunStatus.FAILED)
                        run.status = RunStatus.FAILED
            elif slurm_status == ServiceStatus.ERROR:
                self.registry.update_status(run.id, RunStatus.FAILED)
                run.status = RunStatus.FAILED
        
        return run
    
    def get_run_results(self, run_id: str) -> Optional[dict]:
        """
        Get the results of a completed run.
        
        Args:
            run_id: Run ID
            
        Returns:
            Results dictionary or None
        """
        run = self.registry.get(run_id)
        
        if not run.results_path:
            return None
        
        results_file = Path(run.results_path) / "benchmark_results.json"
        if not results_file.exists():
            return None
        
        try:
            with open(results_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read results: {e}")
            return None
    
    def list_runs(self, active_only: bool = False) -> list[ClientRun]:
        """List all client runs."""
        if active_only:
            return self.registry.get_active()
        return self.registry.get_all()
    
    def list_available_recipes(self) -> list[str]:
        """List available client recipes."""
        return self.recipe_loader.list_recipes(RecipeType.CLIENT)
    
    def get_run_logs(self, run_id: str, lines: int = 100, log_type: str = "output") -> str:
        """Get logs for a client run."""
        run = self.registry.get(run_id)
        work_dir = self._get_work_dir(run.id)
        
        if log_type == "error":
            return self.orchestrator.get_job_error(run.slurm_job_id, work_dir, lines)
        else:
            return self.orchestrator.get_job_output(run.slurm_job_id, work_dir, lines)


# Global client manager instance
_manager: Optional[ClientManager] = None


def get_client_manager() -> ClientManager:
    """Get the global client manager instance."""
    global _manager
    if _manager is None:
        _manager = ClientManager()
    return _manager
