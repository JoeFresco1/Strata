from __future__ import annotations

import subprocess
import time
from pathlib import Path
import json

import requests

from strata.config import AppConfig, ModelProfile, resolve_llama_server_executable, resolve_reasoning_settings


class ServerManagerError(RuntimeError):
    pass


class LlamaServerManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.runtime_dir = Path(__file__).resolve().parent.parent / ".runtime"
        self.logs_dir = self.runtime_dir / "logs"
        self.pid_file = self.runtime_dir / "llama-server.pid"
        self.meta_file = self.runtime_dir / "llama-server.meta.json"
        self.stdout_log = self.logs_dir / "llama-server.stdout.log"
        self.stderr_log = self.logs_dir / "llama-server.stderr.log"
        self.base_url = config.llama_base_url.rstrip("/")
        self.server_exe = resolve_llama_server_executable(config)

    def refresh_runtime_settings(self) -> None:
        """Re-read endpoint and executable settings after runtime config changes."""
        self.base_url = self.config.llama_base_url.rstrip("/")
        self.server_exe = resolve_llama_server_executable(self.config)

    def get_loaded_model_alias(self) -> str | None:
        try:
            response = requests.get(f"{self.base_url}/v1/models", timeout=5)
            response.raise_for_status()
        except requests.RequestException:
            return None
        body = response.json()
        data = body.get("data") or []
        if not data:
            return None
        return data[0].get("id")

    def ensure_model_loaded(
        self,
        profile: ModelProfile,
        timeout_seconds: int = 420,
        *,
        thinking_enabled: bool = False,
    ) -> None:
        if self.server_exe is None:
            raise ServerManagerError("No llama-server executable detected.")
        if profile.path is None:
            managed_profile = self.get_managed_profile(profile.alias)
            if managed_profile is None:
                return
            profile = managed_profile
        current_alias = self.get_loaded_model_alias()
        desired_mode, desired_format, desired_budget = resolve_reasoning_settings(self.config, thinking_enabled)
        current_meta = self._read_meta()
        if (
            current_alias == profile.alias
            and current_meta is not None
            and current_meta.get("reasoning_mode") == desired_mode
            and current_meta.get("reasoning_format") == desired_format
            and int(current_meta.get("reasoning_budget", desired_budget)) == desired_budget
        ):
            return
        self.stop_managed_server()
        current_alias = self.get_loaded_model_alias()
        if current_alias is not None and current_alias != profile.alias:
            raise ServerManagerError(
                f"llama.cpp is already serving '{current_alias}' and was not started by Strata. "
                "Stop that server before switching models."
            )
        if current_alias == profile.alias and current_meta is None:
            raise ServerManagerError(
                "llama.cpp is already running with the requested model, but Strata cannot verify its thinking mode. "
                "Stop that server first so Strata can restart it with the requested setting."
            )
        self._start_server(profile, thinking_enabled=thinking_enabled)
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            time.sleep(5)
            alias = self.get_loaded_model_alias()
            if alias == profile.alias:
                return
        raise ServerManagerError(
            f"Failed to load model '{profile.display_name}'. Check {self.stderr_log} for details."
        )

    def stop_managed_server(self) -> None:
        if not self.pid_file.exists():
            return
        try:
            pid = int(self.pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            self.pid_file.unlink(missing_ok=True)
            return
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.pid_file.unlink(missing_ok=True)
        self.meta_file.unlink(missing_ok=True)
        time.sleep(2)

    def _start_server(self, profile: ModelProfile, *, thinking_enabled: bool) -> None:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        reasoning_mode, reasoning_format, reasoning_budget = resolve_reasoning_settings(
            self.config,
            thinking_enabled,
        )
        command = [
            str(self.server_exe),
            "-m",
            str(profile.path),
            "-c",
            str(self.config.context_size),
            "-ngl",
            str(self.config.gpu_layers),
            "--host",
            self.config.llama_host,
            "--port",
            str(self.config.llama_port),
            "--reasoning",
            reasoning_mode,
            "--reasoning-format",
            reasoning_format,
            "--reasoning-budget",
            str(reasoning_budget),
            "--alias",
            profile.alias,
            "--jinja",
            "--no-ui",
        ]
        stdout_handle = open(self.stdout_log, "w", encoding="utf-8")
        stderr_handle = open(self.stderr_log, "w", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=str(Path(__file__).resolve().parent.parent),
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creation_flags,
        )
        stdout_handle.close()
        stderr_handle.close()
        self.pid_file.write_text(str(process.pid), encoding="utf-8")
        self.meta_file.write_text(
            json.dumps(
                {
                    "alias": profile.alias,
                    "model_path": str(profile.path),
                    "reasoning_mode": reasoning_mode,
                    "reasoning_format": reasoning_format,
                    "reasoning_budget": reasoning_budget,
                    "thinking_enabled": thinking_enabled,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _read_meta(self) -> dict[str, object] | None:
        if not self.meta_file.exists():
            return None
        try:
            return json.loads(self.meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def get_managed_profile(self, alias: str) -> ModelProfile | None:
        meta = self._read_meta()
        if meta is None:
            return None
        if str(meta.get("alias", "")) != alias:
            return None
        model_path = meta.get("model_path")
        if not isinstance(model_path, str) or not model_path:
            return None
        path = Path(model_path)
        if not path.exists():
            return None
        return ModelProfile(alias=alias, display_name=alias, path=path)
