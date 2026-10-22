"""开发绑定必须保留批准边界，重启不得重复创建服务身份。"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("dev_speech", Path(__file__).resolve().parents[1] / "scripts/dev-speech.py")
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


class DevSpeechTests(unittest.TestCase):
    def source(self):
        key = "v-voice.auto.orin-voice-native-bounded-v1.infer"
        return {"binding": {"models": {"sensevoice-int8": key, "kokoro-multilang": key},
            "input_limits_version": 1, "model_limits": {"sensevoice-int8": {"input_bytes": 1048576},
                "kokoro-multilang": {"text_characters": 512}}, "token": "old-token",
            "executor_token": "old-executor-token", "gateway_executors": {"model": "gateway"}},
            "executors": [{"id": key, "node_id": "local", "app_id": "com.ictrek.v-voice",
                "task_type": "model.infer", "resources": {"memory_mib": 2304},
                "upstream_urls": ["http://v-voice-backend:7070/v1"]}]}

    def test_development_identity_keeps_budget_and_limits_without_old_credentials(self):
        source = self.source()
        original = copy.deepcopy(source)
        binding, definitions = dev.development_binding(source, "local")
        self.assertEqual(source, original)
        self.assertEqual(binding["app_id"], dev.APP_ID)
        self.assertEqual(binding["model_limits"], original["binding"]["model_limits"])
        self.assertEqual(next(iter(definitions.values()))["resources"], original["executors"][0]["resources"])
        self.assertEqual(binding["gateway_executors"], {})
        self.assertNotIn("token", binding)
        self.assertNotIn("executor_token", binding)

    def test_unapproved_models_and_other_nodes_are_rejected(self):
        source = self.source()
        source["binding"]["models"]["speaker-campplus-zh-en"] = "new"
        with self.assertRaises(RuntimeError):
            dev.development_binding(source, "local")
        with self.assertRaises(RuntimeError):
            dev.development_binding(self.source(), "other-node")

    def test_restart_reuses_identity_and_refuses_changed_executor(self):
        binding, definitions = dev.development_binding(self.source(), "local")
        existing = [{"id": key, "state": "enabled", "definition": value} for key, value in definitions.items()]
        identities = []
        def request(token, path, body=None):
            if path == "/management":
                return {"executors": existing}
            if path == "/service-identities":
                identities.append(body)
                return {"token": "a" * 64}
            if path == "/executors":
                self.assertEqual(token, "a" * 64)
                return list(definitions.values())
            self.fail("不应覆盖执行器或再次创建身份: " + path)
        with tempfile.TemporaryDirectory() as directory, patch.object(dev, "request", side_effect=request):
            state = Path(directory)
            dev.configure_scheduler(state, copy.deepcopy(binding), definitions, "admin")
            saved = json.loads((state / "scheduler.local.json").read_text())
            self.assertEqual(saved["token"], "a" * 64)
            self.assertEqual((state / "scheduler.local.json").stat().st_mode & 0o777, 0o600)
            dev.configure_scheduler(state, copy.deepcopy(binding), definitions, "admin")
            self.assertEqual(len(identities), 1)
            existing[0]["state"] = "disabled"
            with self.assertRaises(RuntimeError):
                dev.configure_scheduler(state, copy.deepcopy(binding), definitions, "admin")

    def test_remote_target_cannot_be_mistaken_for_local_runtime(self):
        with patch.object(dev, "docker_host_addresses", return_value=["192.168.1.207"]):
            dev.local_endpoint("http://192.168.1.207:22700")
            for url in ["http://192.168.1.208:22700", "https://127.0.0.1:22700", "http://127.0.0.1:7070"]:
                with self.assertRaises(RuntimeError):
                    dev.local_endpoint(url)
