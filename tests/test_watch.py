import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api import ApiClient, ApiError, AuthenticationError
from watch.backend import WatchBackend
from watch.config import WatchExtractionConfig
from watch.frontend import WatchView
from watch.kit_lookup import check_kit
from watch.watch_connection import WatchConnectionManager
from core.registration import RegistrationError


class KitTests(unittest.TestCase):
    def setUp(self):
        self.client = ApiClient("https://example.test")
        self.client.session = SimpleNamespace(access_token="test-jwt")

    @patch("api.client.requests.request")
    def test_lookup_uses_jwt_and_encoded_kit(self, request):
        response = MagicMock(status_code=200)
        response.json.return_value = {"exists": True, "kit_type": "free_living",
            "participant": {"code": "JJJ-78-8763", "study_type": "arritmia"},
            "smartwatches": [{"name": "Watch_10"}]}
        request.return_value = response
        result = check_kit(self.client, "Kit 17")
        self.assertEqual(result["participant"], "JJJ-78-8763")
        self.assertEqual(result["context"], "free_living")
        self.assertEqual(result["watches"], ["Watch_10"])
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer test-jwt")
        self.assertEqual(request.call_args.args, ("GET", "https://example.test/api/v1/installer/by-kit/Kit%2017/check"))

    @patch("api.client.requests.request")
    def test_offline_never_sends_request(self, request):
        self.client.enter_offline("Operator")
        with self.assertRaises(AuthenticationError):
            check_kit(self.client, "Kit_17")
        request.assert_not_called()

    @patch("api.client.requests.request")
    def test_expired_token_is_not_retried_anonymously(self, request):
        request.return_value = MagicMock(status_code=401)
        with self.assertRaises(AuthenticationError):
            check_kit(self.client, "Kit_17")
        self.assertIsNone(self.client.session)
        request.assert_called_once()

    def test_response_validation_and_optional_fields(self):
        with patch.object(self.client, "request_json") as request:
            for data in (None, {}, {"exists": "true"}, {"exists": True, "participant": []},
                         {"exists": True, "smartwatches": [None]}):
                request.return_value = data
                with self.subTest(data=data), self.assertRaises(ApiError):
                    check_kit(self.client, "Kit_17")
            request.return_value = {"exists": False}
            self.assertFalse(check_kit(self.client, "Kit_17")["exists"])
            request.return_value = {"exists": True, "kit_type": "unknown"}
            self.assertEqual(check_kit(self.client, "Kit_17"),
                             {"exists": True, "participant": "", "context": "", "watches": []})


class BackendTests(unittest.TestCase):
    def setUp(self):
        # Avoid constructor filesystem effects; exercise actual resolver/extraction logic.
        self.backend = WatchBackend.__new__(WatchBackend)
        self.backend.android_fs = MagicMock()
        self.backend.adb = MagicMock()
        self.backend.config = WatchExtractionConfig()
        self.backend.connection_manager = MagicMock()
        self.backend.connection_manager.get_connected_devices.return_value = ["192.168.1.2:5555"]
        self.backend.get_existing_watch_source_paths = MagicMock(return_value=["/sdcard/Documents"])
        self.backend.copy_watch_sources_to_staging = MagicMock()
        self.registration = patch("watch.backend.RegistrationResolver").start()
        self.addCleanup(patch.stopall)
        self.registration.return_value.resolve.return_value = None
        self.backend.android_fs.list_files.return_value = []

    def extract(self, **kwargs):
        return self.backend.extract_documents(watch_number="", watch_name="", ip="192.168.1.2",
            pairing_port="", connect_port="5555", collection_context="free_living",
            expected_participant_id="JJJ-78-8763", **kwargs)

    def test_manual_identity_when_absent(self):
        selected, metadata = self.backend.resolve_watch_id_from_sources(["/sdcard/Documents"],
            expected_participant_id=" jjj-78-8763 ")
        self.assertEqual(selected, "JJJ-78-8763")
        self.assertEqual(metadata["resolution_source"], "form_input")

    def test_conflicting_registration_stops_before_copy(self):
        self.registration.return_value.resolve.return_value = {"participant_id": "ABC-12-3456"}
        with self.assertRaisesRegex(RuntimeError, "Conflito de participante"):
            self.extract()
        self.backend.copy_watch_sources_to_staging.assert_not_called()

    def test_any_conflicting_filename_id_blocks(self):
        self.backend.android_fs.list_files.return_value = ["JJJ-78-8763.csv", "ABC-12-3456.csv"]
        with self.assertRaisesRegex(RuntimeError, "Conflito de participante"):
            self.extract()
        self.backend.copy_watch_sources_to_staging.assert_not_called()

    def test_invalid_registration_is_not_manual_fallback(self):
        self.registration.return_value.resolve.side_effect = RegistrationError("Cadastro inválido")
        with self.assertRaises(RegistrationError):
            self.extract()
        self.backend.copy_watch_sources_to_staging.assert_not_called()

    def test_optional_watch_and_registration_routing(self):
        self.registration.return_value.resolve.return_value = {
            "participant_id": "JJJ-78-8763", "collection_context": "in_clinic",
            "kit_type": "IC", "source_path": "/sdcard/Documents/registration.json"}
        self.backend.copy_watch_sources_to_staging.return_value = (Path("staging"), Path("archive.zip"), [])
        self.backend.metadata_builder = MagicMock()
        with patch("watch.backend.save_active_registration"), patch("watch.backend.write_json_metadata"), \
             patch("watch.backend.WatchDocumentCopier.create_zip_archive", return_value=Path("archive.zip")), \
             patch("watch.backend.WatchDocumentCopier.cleanup_staging"):
            result = self.extract()
        self.assertEqual(result["watch_name"], "Não informado")
        self.assertEqual(result["collection_context"], "in_clinic")
        self.assertIn("difere", result["context_warning"])
        self.assertEqual(self.backend.format_watch_name("10"), "Relógio - 010")

    def test_device_states_do_not_raise(self):
        adb = MagicMock()
        adb.run.return_value.stdout = "List of devices attached\n192.168.1.2:5555\tdevice model:Watch\nusb\tunauthorized\nold\toffline\nnew\tunknown\n"
        result = WatchConnectionManager(adb).list_device_statuses()
        self.assertEqual([item["state"] for item in result], ["device", "unauthorized", "offline", "unknown"])


class WatchUiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.client = ApiClient("https://example.test")
        self.client.enter_offline("Operator")
        self.backend = MagicMock()
        self.backend.config = WatchExtractionConfig()
        self.backend.connection_manager = WatchConnectionManager(MagicMock())
        with patch.object(WatchView, "refresh_network"), patch.object(WatchView, "refresh_devices"):
            self.view = WatchView(self.root, self.client, self.backend)
        self.view.outer.pack(fill="both", expand=True)

    def test_offline_manual_fields_and_no_verification(self):
        self.view.vars["kit"].set("Kit_17")
        self.view.vars["participant"].set("JJJ-78-8763")
        self.assertEqual(str(self.view.verify_button["state"]), "disabled")
        with patch("watch.frontend.check_kit") as lookup:
            self.view.verify_kit()
            lookup.assert_not_called()
        self.assertIn("identificação manual", self.view.kit_status.get())

    def test_status_styles_and_layout(self):
        view = self.view
        view.kit_status.set("Kit encontrado")
        view.participant_status.set("Nenhum participante associado")
        self.assertEqual(view.kit_status_label["style"], "Watch.Found.TLabel")
        self.assertEqual(view.participant_status_label["style"], "Watch.Missing.TLabel")
        self.assertEqual({int(button["width"]) for button in
                          (view.verify_button, view.network_button, view.pair_button, view.connect_button)}, {12})
        self.assertEqual(view.inspect_button.master, view.extract_button.master)
        self.assertEqual(view.inspect_button.grid_info()["row"], view.extract_button.grid_info()["row"])
        watch_entry = next(widget for widget in view.inputs
                           if getattr(widget, "variable", None) is view.vars["watch"])
        self.assertGreater(view.kit_status_label.grid_info()["row"], watch_entry.grid_info()["row"])
        self.root.update_idletasks()
        # Allow room for the outer vertical scrollbar at the 900px minimum.
        self.assertLessEqual(view.frame.winfo_reqwidth(), 880)

    def test_button_validity_and_busy_recovery(self):
        view = self.view
        for key, value in {"ip": "192.168.1.2", "pair_port": "5555", "code": "123456"}.items():
            view.vars[key].set(value)
        self.assertEqual(str(view.pair_button["state"]), "normal")
        view.vars["pair_port"].set("65536")
        self.assertEqual(str(view.pair_button["state"]), "disabled")
        view.busy = True
        view.update_controls()
        self.assertEqual(str(view.connect_button["state"]), "disabled")

    def test_stale_lookup_and_inflight_edits(self):
        view = self.view
        self.client.offline_session = None
        self.client.session = SimpleNamespace(access_token="jwt")
        view.vars["kit"].set("Kit_17")
        result = {"exists": True, "participant": "JJJ-78-8763", "context": "free_living", "watches": ["Watch_10"]}
        with patch.object(view, "submit") as submit:
            view.verify_kit()
            view.vars["kit"].set("Kit_18")
            submit.call_args.args[1](result)
            self.assertEqual(view.vars["participant"].get(), "")
            view.verify_kit()
            view.vars["participant"].set("ABC-12-3456")
            submit.call_args.args[1](result)
            self.assertEqual(view.vars["participant"].get(), "ABC-12-3456")

    def test_missing_lookup_fields_preserve_manual_identification(self):
        view = self.view
        self.client.offline_session = None
        self.client.session = SimpleNamespace(access_token="jwt")
        view.vars["kit"].set("Kit_17")
        view.vars["participant"].set("ABC-12-3456")
        with patch.object(view, "submit") as submit:
            view.verify_kit()
            self.assertEqual(str(view.connect_button["state"]), "disabled")
            submit.call_args.args[1]({"exists": False, "participant": "", "context": "", "watches": []})
        self.assertEqual(view.vars["participant"].get(), "ABC-12-3456")

    def test_pairing_survives_discovery_failure(self):
        view = self.view
        view.vars["ip"].set("192.168.1.2")
        self.backend.pair_watch.return_value = "Successfully paired to 192.168.1.2:5555"
        self.backend.get_connect_port.side_effect = RuntimeError("Porta não encontrada")
        with patch.object(view, "submit") as submit, patch.object(view, "refresh_devices"):
            view.pair()
            work, success, _failure = submit.call_args.args
            success(work())
        self.assertIn("192.168.1.2", view.paired)
        self.assertIn("Pareamento confirmado", view.pair_status.get())
        self.assertIn("Porta não encontrada", view.pair_status.get())

    def test_destroy_releases_prompt_and_ignores_late_callbacks(self):
        self.view.outer.destroy()
        self.assertTrue(self.view.closed.is_set())
        self.assertIsNone(self.view.prompt_id("Missing", None))
        callback = MagicMock()
        self.view.events.put((callback, None))
        self.view.poll()
        callback.assert_not_called()
