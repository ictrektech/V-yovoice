"""统一应用接入回归：历史配置名不能再次变成独立应用依赖。"""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_model_repository_uses_unified_scheduler_without_moving_existing_weights():
    from vvoice.config import Settings

    assert Settings.__dataclass_fields__['model_hub_api_url'].default == 'http://v-scheduler-model-hub:6005'
    compose = (ROOT / 'ictrek.app/src/docker-compose.yml').read_text()
    assert 'http://v-scheduler-model-hub:6005' in compose
    assert '${MODEL_HUB_SHARED_MODELS_PATH:-/data/vos_workspace/model_hub}:/modelhub:ro' in compose
    manifest = (ROOT / 'ictrek.app/src/manifest.yml').read_text()
    assert '- id: com.ictrek.v-scheduler' in manifest
    assert '- id: com.ictrek.model-hub' not in manifest
    assert '- id: com.ictrek.v-router' not in manifest


def test_model_management_locales_name_scheduler_instead_of_retired_application():
    for locale in ('en', 'zh-cn', 'zh-tw'):
        messages = json.loads((ROOT / f'web/src/shared/i18n/catalogs/{locale}.json').read_text())
        for key in ('@vvoice.models.sharedHint', '@vvoice.models.importRequired', '@vvoice.runtime.unloadHint'):
            text = messages[key]['defaultMessage']
            assert 'V-Scheduler' in text
            assert 'Model Hub' not in text
