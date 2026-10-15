import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location("voice_package", Path(__file__).with_name("package.py"))
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class DependencyTests(unittest.TestCase):
    def manifest(self, app="com.ictrek.model-hub"):
        return {"dependencies": {"apps": [{"id": app, "version": "latest"}]}}

    def store_response(self, version="0.0.95", size=1280):
        return {"code": 0, "data": {"id": "com.ictrek.model-hub", "current_version": version,
                "versions": [version], "app_tar_gz": {"size": size,
                "download_path": f"appstore/apps/com.ictrek.model-hub/{version}/app.tar.gz"}}}

    def opener(self, record):
        def open_url(request, **kwargs):
            url = request if isinstance(request, str) else request.full_url
            if url.startswith("https://api.github.com/"):
                raise HTTPError(url, 404, "private", {}, None)
            if not isinstance(request, str) and request.get_method() == "HEAD":
                response = io.BytesIO()
                response.headers = {"Content-Length": "1280"}
                return response
            return io.BytesIO(json.dumps(record).encode())
        return open_url

    def test_public_github_release(self):
        release = {"tag_name": "v0.0.95", "published_at": "2026-10-15", "assets": [{"name": "model_hub_0.0.95_pull.tar"}]}
        manifest = self.manifest()
        with patch.object(package.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(release).encode())):
            package.resolve_dependencies(manifest)
        self.assertEqual(manifest["dependencies"]["apps"][0]["version"], ">=0.0.95")

    def test_private_repo_uses_live_store_and_actual_archive(self):
        manifest = self.manifest()
        with patch.dict(os.environ, {"VVOICE_APPSTORE_API_URL": "http://127.0.0.1:18899"}), patch.object(package.urllib.request, "urlopen", side_effect=self.opener(self.store_response())):
            package.resolve_dependencies(manifest)
        self.assertEqual(manifest["dependencies"]["apps"][0]["version"], ">=0.0.95")

    def test_invalid_or_stale_store_record_fails_closed(self):
        for change in ("missing", "wrong_id", "stale", "missing_archive", "wrong_path"):
            record = self.store_response()
            if change == "missing": record["code"] = 20205
            if change == "wrong_id": record["data"]["id"] = "com.other"
            if change == "stale": record["data"]["versions"].append("0.0.96")
            if change == "missing_archive": record["data"]["app_tar_gz"]["size"] = 0
            if change == "wrong_path": record["data"]["app_tar_gz"]["download_path"] = "../../secret"
            with self.subTest(change=change), patch.dict(os.environ, {"VVOICE_APPSTORE_API_URL": "http://127.0.0.1:18899"}), patch.object(package.urllib.request, "urlopen", side_effect=self.opener(record)):
                with self.assertRaises(RuntimeError): package.resolve_dependencies(self.manifest())

    def test_protocol_minimum_is_not_relaxed(self):
        with patch.dict(os.environ, {"VVOICE_APPSTORE_API_URL": "http://127.0.0.1:18899"}), patch.object(package.urllib.request, "urlopen", side_effect=self.opener(self.store_response("0.0.93"))):
            with self.assertRaisesRegex(RuntimeError, "required contract"):
                package.resolve_dependencies(self.manifest())

    def test_private_repo_without_tunnel_fails(self):
        with patch.dict(os.environ, {"VVOICE_APPSTORE_API_URL": ""}), patch.object(package.urllib.request, "urlopen", side_effect=self.opener(self.store_response())):
            with self.assertRaisesRegex(RuntimeError, "tunnel required"):
                package.resolve_dependencies(self.manifest())

    def test_actual_archive_size_must_match(self):
        with patch.object(package.urllib.request, "urlopen", side_effect=self.opener(self.store_response(size=2560))):
            with self.assertRaisesRegex(RuntimeError, "unavailable or changed"):
                package.appstore_version("com.ictrek.model-hub", "http://127.0.0.1:18899")

    def test_tunnel_cannot_redirect_verification(self):
        with self.assertRaisesRegex(RuntimeError, "loopback"):
            package.appstore_version("com.ictrek.model-hub", "https://unapproved.example")


if __name__ == "__main__":
    unittest.main()
