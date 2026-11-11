from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FULL_TRANSCRIPTION_CONFIGS = (
    "VVOICE_MAX_UPLOAD_MB",
    "VVOICE_FULL_TRANSCRIPTION_MAX_SECONDS",
    "VVOICE_FULL_TRANSCRIPTION_TIMEOUT_SECONDS",
    "VVOICE_FULL_TRANSCRIPTION_DECODE_TIMEOUT_SECONDS",
    "VVOICE_FULL_TRANSCRIPTION_MAX_PARTS",
    "VVOICE_FULL_TRANSCRIPTION_MAX_SOURCE_SAMPLE_RATE",
    "VVOICE_FULL_TRANSCRIPTION_MAX_SOURCE_CHANNELS",
)


def test_full_transcription_vos_configs_reach_container_environment() -> None:
    configs = {
        row["name"]: row
        for row in yaml.safe_load(
            (ROOT / "ictrek.app/src/configs.yml").read_text()
        )["configs"]
    }
    environment = yaml.safe_load(
        (ROOT / "ictrek.app/src/docker-compose.yml").read_text()
    )["x-vvoice-env"]
    for name in FULL_TRANSCRIPTION_CONFIGS:
        row = configs[name]
        assert row["type"] == "integer"
        assert environment[name] == f"${{{name}:-{row['default']}}}"
