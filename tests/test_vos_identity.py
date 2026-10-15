"""发行身份与图标不能随创作界面更换而改变。"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v_voice_logo_is_preserved_in_both_interfaces_and_package():
    expected = "1bbcbdd36858d396f86b5894720003de39441029340ce625795417ae2fa51db0"
    for relative in ("ictrek.app/src/icon.png", "frontend/public/icon.png", "web/public/v-voice.png"):
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_release_identity_and_six_profiles_are_retained():
    manifest = (ROOT / "ictrek.app/src/manifest.yml").read_text()
    assert "id: com.ictrek.v-voice\n" in manifest
    assert "zh-CN: V-Voice\n" in manifest and "en: V-Voice\n" in manifest
    for name in ("amd", "amd-cuda", "arm", "arm-cuda", "l4t", "thor"):
        assert f"  - name: {name}\n" in manifest
    workflow = (ROOT / ".github/workflows/vos-release.yml").read_text()
    assert '"vos-v-voice-v*"' in workflow
    assert "v_voice_${VERSION}_pull.tar" in workflow
    assert "Publish package to VOS App Store" in workflow
