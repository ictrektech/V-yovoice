from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_id: str = os.getenv("VVOICE_APP_ID", "com.ictrek.v-voice")
    app_version: str = os.getenv("APP_VERSION", "dev")
    profile: str = os.getenv("VVOICE_PROFILE", "local")
    host: str = os.getenv("VVOICE_HOST", "0.0.0.0")
    port: int = int(os.getenv("VVOICE_PORT", "7070"))
    modelhub_root: Path = Path(os.getenv("MODEL_HUB_SHARED_MODELS_PATH", "/modelhub"))
    model_hub_api_url: str = os.getenv("MODEL_HUB_API_URL", "http://model-hub-backend:5005").rstrip("/")
    catalog_path: Path = Path(os.getenv("VVOICE_CATALOG_PATH", str(Path(__file__).resolve().parents[1] / "catalog" / "models.json")))
    data_dir: Path = Path(os.getenv("VVOICE_DATA_DIR", "/data"))
    provider: str = os.getenv("VVOICE_PROVIDER", "auto").lower()
    num_threads: int = max(1, int(os.getenv("VVOICE_NUM_THREADS", str(os.cpu_count() or 2))))
    max_loaded_models: int = max(1, int(os.getenv("VVOICE_MAX_LOADED_MODELS", "2")))
    max_concurrent_inference: int = max(1, int(os.getenv("VVOICE_MAX_CONCURRENT_INFERENCE", "2")))
    max_concurrent_per_model: int = max(1, int(os.getenv("VVOICE_MAX_CONCURRENT_PER_MODEL", "2")))
    max_upload_mb: int = max(1, int(os.getenv("VVOICE_MAX_UPLOAD_MB", "200")))
    vad_split_seconds: float = float(os.getenv("VVOICE_VAD_SPLIT_SECONDS", "30"))
    cpu_models: tuple[str, ...] = tuple(
        model.strip() for model in os.getenv("VVOICE_CPU_MODELS", "").split(",") if model.strip()
    )


settings = Settings()
