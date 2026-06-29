from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    """Read the public STRATA name while preserving legacy SPECFORGE compatibility."""
    value = os.getenv(f"STRATA_{name}")
    if value is not None:
        return value
    return os.getenv(f"SPECFORGE_{name}", default)


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
EXPORTS_DIR = ROOT_DIR / "exports"
DEFAULT_DB_PATH = DATA_DIR / "specforge.db"
DEFAULT_PROMPTS_PATH = ROOT_DIR / "prompts.json"
DEFAULT_POSTGRES_URL = "postgresql://postgres@127.0.0.1:55433/specforge"
DEFAULT_POSTGRES_ADMIN_URL = "postgresql://postgres@127.0.0.1:55433/postgres"
DEFAULT_MODEL_ROOT = Path(_env("MODEL_ROOT", str(Path.home() / ".cache" / "strata" / "models")) or "")
DEFAULT_LLAMA_SERVER_CANDIDATES = [Path("llama-server"), Path("llama-server.exe")]

EMBEDDING_MODEL_PRESETS = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/all-mpnet-base-v2",
    "BAAI/bge-small-en-v1.5",
    "BAAI/bge-base-en-v1.5",
    "nomic-ai/nomic-embed-text-v1.5",
    "mixedbread-ai/mxbai-embed-large-v1",
]


@dataclass(slots=True)
class AppConfig:
    database_backend: str = _env("DB_BACKEND", "postgres") or "postgres"
    database_url: str = _env("DATABASE_URL", DEFAULT_POSTGRES_URL) or DEFAULT_POSTGRES_URL
    postgres_admin_url: str = _env("POSTGRES_ADMIN_URL", DEFAULT_POSTGRES_ADMIN_URL) or DEFAULT_POSTGRES_ADMIN_URL
    db_path: Path = Path(_env("DB_PATH", str(DEFAULT_DB_PATH)) or DEFAULT_DB_PATH)
    exports_dir: Path = Path(_env("EXPORTS_DIR", str(EXPORTS_DIR)) or EXPORTS_DIR)
    llama_base_url: str = os.getenv("LLAMA_BASE_URL", "http://127.0.0.1:8080")
    llama_timeout_seconds: int = int(os.getenv("LLAMA_TIMEOUT_SECONDS", "180"))
    model_root: Path = DEFAULT_MODEL_ROOT
    model_name: str = _env("MODEL_NAME", "local-model") or "local-model"
    model_api_key: str = _env("MODEL_API_KEY", "") or ""
    preferred_model_path: str | None = _env("MODEL_PATH")
    llama_server_exe: str = os.getenv("LLAMA_SERVER_EXE", "")
    context_size: int = int(os.getenv("LLAMA_CONTEXT_SIZE", "32768"))
    max_output_tokens: int = int(os.getenv("LLAMA_MAX_OUTPUT_TOKENS", "1800"))
    gpu_layers: int = int(os.getenv("LLAMA_GPU_LAYERS", "35"))
    default_temperature: float = float(os.getenv("LLAMA_TEMPERATURE", "0.4"))
    default_top_p: float = float(os.getenv("LLAMA_TOP_P", "0.9"))
    reasoning_mode: str = os.getenv("LLAMA_REASONING_MODE", "off")
    reasoning_format: str = os.getenv("LLAMA_REASONING_FORMAT", "none")
    reasoning_budget: int = int(os.getenv("LLAMA_REASONING_BUDGET", "0"))
    reasoning_enabled_budget: int = int(os.getenv("LLAMA_REASONING_ENABLED_BUDGET", "-1"))
    reasoning_enabled_format: str = os.getenv("LLAMA_REASONING_ENABLED_FORMAT", "deepseek")
    llama_host: str = os.getenv("LLAMA_HOST", "127.0.0.1")
    llama_port: int = int(os.getenv("LLAMA_PORT", "8080"))
    prompts_path: Path = Path(_env("PROMPTS_PATH", str(DEFAULT_PROMPTS_PATH)) or DEFAULT_PROMPTS_PATH)
    embeddings_enabled: bool = (_env("EMBEDDINGS_ENABLED", "true") or "true").strip().lower() in {"1", "true", "yes", "on"}
    embeddings_model_name: str = _env("EMBEDDINGS_MODEL", "sentence-transformers/all-MiniLM-L6-v2") or "sentence-transformers/all-MiniLM-L6-v2"
    embeddings_insecure_download_fallback: bool = (_env("EMBEDDINGS_INSECURE_DOWNLOAD_FALLBACK", "false") or "false").strip().lower() in {"1", "true", "yes", "on"}
    pillar_similarity_threshold: float = float(_env("PILLAR_SIMILARITY_THRESHOLD", "0.78") or "0.78")
    pillar_similarity_block_threshold: float = float(_env("PILLAR_SIMILARITY_BLOCK_THRESHOLD", "0.9") or "0.9")
    pillar_similarity_top_k: int = int(_env("PILLAR_SIMILARITY_TOP_K", "3") or "3")
    allowed_origins: tuple[str, ...] = tuple(
        item.strip() for item in (os.getenv("STRATA_ALLOWED_ORIGINS") or "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173").split(",")
        if item.strip()
    )


@dataclass(slots=True)
class ModelProfile:
    alias: str
    display_name: str
    path: Path | None


def ensure_runtime_dirs(config: AppConfig) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.exports_dir.mkdir(parents=True, exist_ok=True)
    (ROOT_DIR / ".runtime" / "logs").mkdir(parents=True, exist_ok=True)


def using_postgres(config: AppConfig) -> bool:
    """Return whether SpecForge should use PostgreSQL as the active database backend."""
    return config.database_backend.strip().lower() == "postgres"


def resolve_database_target(config: AppConfig) -> str | Path:
    """Return the active database target for the configured backend."""
    if using_postgres(config):
        return config.database_url
    return config.db_path


def describe_database_target(config: AppConfig) -> str:
    """Return a human-readable description of the active database target."""
    target = resolve_database_target(config)
    return str(target)


def discover_gguf_models(model_root: Path | None = None) -> list[Path]:
    root = model_root or DEFAULT_MODEL_ROOT
    if not root.exists():
        return []
    return sorted(root.rglob("*.gguf"))


def choose_default_model(model_paths: list[Path]) -> Path | None:
    if not model_paths:
        return None
    ranked_paths = sorted(
        model_paths,
        key=lambda path: (
            0 if "no-thinking" in str(path).lower() else 1,
            0 if "qwen 3.6 27b" in str(path).lower() else 1,
            0 if "qwen" in str(path).lower() else 1,
            0 if "q3_k_m" in str(path).lower() else 1,
            0 if "qwen3.5-9b-q6_k" in str(path).lower() else 1,
            len(str(path)),
        ),
    )
    return ranked_paths[0]


def resolve_model_path(config: AppConfig) -> Path | None:
    if config.preferred_model_path:
        preferred = Path(config.preferred_model_path)
        if preferred.exists():
            return preferred
    return choose_default_model(discover_gguf_models(config.model_root))


def resolve_llama_server_executable(config: AppConfig) -> Path | None:
    if config.llama_server_exe:
        candidate = Path(config.llama_server_exe)
        if candidate.exists():
            return candidate
    for candidate in DEFAULT_LLAMA_SERVER_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def build_llama_server_command(config: AppConfig, model_path: Path | None) -> str:
    server_exe = resolve_llama_server_executable(config)
    server_part = f'"{server_exe}"' if server_exe is not None else "llama-server"
    if model_path is None:
        return "No GGUF model found. Set SPECFORGE_MODEL_PATH or add a model under the configured model root."
    return (
        f'{server_part} -m "{model_path}" -c {config.context_size} '
        f"-ngl {config.gpu_layers} --host {config.llama_host} --port {config.llama_port} "
        f"--reasoning {config.reasoning_mode} --reasoning-format {config.reasoning_format} "
        f"--reasoning-budget {config.reasoning_budget} "
        f'--alias "{config.model_name}" --jinja --no-ui'
    )


def resolve_reasoning_settings(config: AppConfig, thinking_enabled: bool) -> tuple[str, str, int]:
    if thinking_enabled:
        return ("on", config.reasoning_enabled_format, config.reasoning_enabled_budget)
    return (config.reasoning_mode, config.reasoning_format, config.reasoning_budget)


def _slugify_model_name(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def build_model_profiles(config: AppConfig) -> list[ModelProfile]:
    profiles: list[ModelProfile] = []
    seen_paths: set[Path] = set()
    for path in discover_gguf_models(config.model_root):
        lower_path = str(path).lower()
        if "mmproj" in lower_path:
            continue
        relative = path.relative_to(config.model_root)
        display_name = str(relative.parent / path.name) if relative.parent != Path(".") else path.name
        profiles.append(
            ModelProfile(
                alias=_slugify_model_name(display_name),
                display_name=display_name,
                path=path,
            )
        )
        seen_paths.add(path.resolve())
    if config.preferred_model_path:
        preferred = Path(config.preferred_model_path)
        if preferred.exists():
            resolved = preferred.resolve()
            if resolved not in seen_paths and preferred.suffix.lower() == ".gguf":
                display_name = f"Custom | {preferred.name}"
                profiles.insert(
                    0,
                    ModelProfile(
                        alias=_slugify_model_name(display_name),
                        display_name=display_name,
                        path=preferred,
                    ),
                )
    return profiles


def resolve_default_model_profile(config: AppConfig, profiles: list[ModelProfile]) -> ModelProfile | None:
    preferred_path = resolve_model_path(config)
    if preferred_path is not None:
        for profile in profiles:
            if profile.path == preferred_path:
                return profile
    return profiles[0] if profiles else None
