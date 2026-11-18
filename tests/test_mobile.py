import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api import ApiClient
from api.kit import check_kit_devices
from core.identification import IdentificationContext
from core.registration import RegistrationError
from mobile.backend import MobileBackend
from mobile.config import MobileExtractionConfig
from mobile.frontend import MobileView
from watch.config import WatchExtractionConfig
from watch.frontend import WatchView
from watch.watch_connection import WatchConnectionManager


def resolution(participant="ABC-12-3456", source="ecg_registration"):
    return {"participant_id": participant, "selected_raw_id": participant, "raw_ids": [participant],
            "lookup_key": participant, "lookup_source": source, "matched_in_csv": False,
            "has_multiple_valid_ids": False, "multiple_valid_ids_count": 1,
            "multiple_valid_ids_warning": None}


class MobileBackendTests(unittest.TestCase):
    def setUp(self):
        self.backend = MobileBackend.__new__(MobileBackend)
        self.backend.config = MobileExtractionConfig()
        self.backend.adb = MagicMock()
        self.backend.android_fs = MagicMock()
        self.backend.participant_resolver = MagicMock()
        self.backend.participant_lookup = MagicMock()
        self.backend.document_copier = MagicMock()
        self.backend.metadata_builder = MagicMock()
        self.backend.adb.run.return_value.stdout = "List of devices attached\nphone\tdevice\n"
        self.backend.participant_resolver.resolve_from_phone.return_value = resolution()

    def extract(self, **overrides):
        values = dict(mobile_number="", mobile_name="", collection_context="free_living",
                      expected_participant_id="ABC-12-3456")
        values.update(overrides)
        return self.backend.extract_documents(**values)

    def test_participant_conflict_stops_before_copy(self):
        self.backend.participant_resolver.resolve_from_phone.return_value = resolution("JJJ-78-8763")
        with self.assertRaisesRegex(RuntimeError, "Conflito de participante"):
            self.extract()
        self.backend.document_copier.copy_documents_to_staging.assert_not_called()

    def test_manual_form_fallback_and_invalid_registration(self):
        self.backend.participant_resolver.resolve_from_phone.side_effect = RuntimeError("Sem identificação")
        self.backend.participant_resolver.get_raw_ring_metadata.return_value = {
            "ids_valid": [], "selected_raw_id": None, "has_multiple_valid_ids": False,
            "multiple_valid_ids_count": 0, "multiple_valid_ids_warning": None}
        result = self.backend.resolve_participant(expected_participant_id="ABC-12-3456")
        self.assertEqual(result["participant_id"], "ABC-12-3456")
        self.assertEqual(result["lookup_source"], "form_input")
        self.backend.participant_resolver.resolve_from_phone.side_effect = RegistrationError("Cadastro inválido")
        with self.assertRaises(RegistrationError):
            self.extract()
        self.backend.document_copier.copy_documents_to_staging.assert_not_called()

    def test_multiple_resolved_participants_cannot_silently_choose_first(self):
        result = resolution(source="participants_summary_csv")
        result.update(raw_ids=["Id123", "Id456"], has_multiple_valid_ids=True)
        self.backend.participant_resolver.resolve_from_phone.return_value = result
        self.backend.participant_lookup.resolve.side_effect = [
            {"participant_id": "ABC-12-3456"}, {"participant_id": "JJJ-78-8763"}]
        with self.assertRaisesRegex(RuntimeError, "Conflito de participante"):
            self.extract()
        self.backend.document_copier.copy_documents_to_staging.assert_not_called()

    def test_optional_mobile_and_registration_context_preserve_output_flow(self):
        data = resolution()
        data["registration"] = {"collection_context": "in_clinic", "kit_type": "IC"}
        self.backend.participant_resolver.resolve_from_phone.return_value = data
        self.backend.document_copier.copy_documents_to_staging.return_value = (Path("staging"), Path("out.zip"))
        self.backend.document_copier.create_zip_archive.return_value = Path("out.zip")
        with patch("mobile.backend.save_active_registration"), patch("mobile.backend.write_json_metadata"):
            result = self.extract()
        self.assertEqual(result["mobile_name"], "Não informado")
        self.assertEqual(result["collection_context"], "in_clinic")
        self.assertIn("difere", result["context_warning"])
        self.assertEqual(self.backend.adb.target_device_id, "phone")
        self.backend.document_copier.cleanup_staging.assert_called_once_with(Path("staging"))
        self.assertEqual(self.backend.format_mobile_name("10"), "Mobile - 010")

    def test_missing_type_without_registration_stops_before_copy(self):
        with self.assertRaisesRegex(RuntimeError, "Selecione Free Living"):
            self.extract(collection_context="")
        self.backend.document_copier.copy_documents_to_staging.assert_not_called()

    def test_inspection_conflict_propagates_for_new_form_callers(self):
        self.backend.participant_resolver.resolve_from_phone.return_value = resolution("JJJ-78-8763")
        with self.assertRaisesRegex(RuntimeError, "Conflito de participante"):
            self.backend.inspect_phone_documents(expected_participant_id="ABC-12-3456")

    def test_device_status_and_disconnect_keep_usb_visible(self):
        self.backend.adb.run.return_value.stdout = "List of devices attached\nphone\tdevice\nother\tunauthorized\nold\toffline\n"
        self.assertEqual([d["state"] for d in self.backend.list_device_statuses()], ["device", "unauthorized", "offline"])
        self.backend.disconnect_all_devices()
        self.backend.adb.run.assert_called_with(["disconnect"])
        self.assertIsNone(self.backend.adb.target_device_id)
        self.assertEqual(self.backend.list_device_statuses()[0]["device_id"], "phone")


class MobileUiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.client = ApiClient("https://example.test")
        self.client.enter_offline("Operator")
        self.context = IdentificationContext(self.root)
        self.backend = MagicMock()
        self.backend.get_output_root.side_effect = MobileExtractionConfig().get_output_root
        with patch.object(MobileView, "refresh_devices"):
            self.view = MobileView(self.root, self.client, self.backend, self.context)
        self.view.outer.pack(fill="both", expand=True)

    def prepare(self):
        self.view.vars["kit"].set("Kit_17")
        self.view.vars["participant"].set("ABC-12-3456")
        self.view.devices = [{"device_id": "phone", "state": "device"}]
        self.view.devices_current = True
        self.view.update_controls()

    def test_optional_mobile_and_offline_verification(self):
        self.prepare()
        self.assertEqual(self.view.vars["mobile"].get(), "")
        self.assertEqual(str(self.view.extract_button["state"]), "normal")
        with patch("mobile.frontend.check_kit_devices") as lookup:
            self.view.verify_kit()
            lookup.assert_not_called()
        self.view.vars["participant"].set("")
        self.assertEqual(str(self.view.extract_button["state"]), "disabled")

    def test_shared_context_and_lock_keep_device_labels_separate(self):
        backend = MagicMock()
        backend.config = WatchExtractionConfig()
        backend.connection_manager = WatchConnectionManager(MagicMock())
        with patch.object(WatchView, "refresh_devices"), patch.object(WatchView, "refresh_network"):
            watch = WatchView(self.root, self.client, backend, self.context)
        self.prepare()
        self.view.vars["mobile"].set("Mobile_17")
        self.assertEqual(watch.vars["kit"].get(), "Kit_17")
        self.assertEqual(watch.vars["participant"].get(), "ABC-12-3456")
        self.assertEqual(watch.vars["watch"].get(), "")
        watch.vars["context"].set("in_clinic")
        self.assertEqual(self.view.vars["context"].get(), "in_clinic")
        self.context.busy.set(True)
        self.assertEqual(str(self.view.extract_button["state"]), "disabled")
        self.assertTrue(all(str(entry["state"]) == "disabled" for entry in watch.inputs + self.view.inputs))
        self.context.busy.set(False)
        watch.outer.destroy()
        # Removing a tab must remove its shared-variable traces.
        self.view.vars["participant"].set("JJJ-78-8763")

    def test_progress_stops_after_failed_task_and_duplicate_is_ignored(self):
        with patch.object(self.view, "submit") as submit, patch.object(self.view, "refresh_devices"):
            self.view.run_task(lambda: None, lambda result: None)
            self.assertTrue(self.view.progress_running)
            self.view.run_task(lambda: None, lambda result: None)
            submit.assert_called_once()
            submit.call_args.args[2]("Falha simulada")
        self.assertFalse(self.view.progress_running)
        self.assertFalse(self.context.busy.get())

    def test_equal_columns_layout_and_plain_mobile_placeholder(self):
        self.root.update_idletasks()
        self.assertLessEqual(self.view.frame.winfo_reqwidth(), 880)
        self.assertEqual(self.view.frame.grid_columnconfigure(0)["uniform"],
                         self.view.frame.grid_columnconfigure(1)["uniform"])
        self.assertEqual(self.view.inspect_button.master, self.view.extract_button.master)
        entry = next(widget for widget in self.view.inputs if getattr(widget, "variable", None) is self.view.vars["mobile"])
        self.assertEqual(entry.hint["text"], "Mobile_00")
        self.assertEqual(entry.winfo_class(), "TEntry")

    def test_lookup_autofill_updates_shared_fields_but_uses_smartphones(self):
        self.client.offline_session = None
        self.client.session = SimpleNamespace(access_token="jwt")
        self.view.vars["kit"].set("Kit_17")
        with patch.object(self.view, "submit") as submit, patch("mobile.frontend.check_kit_devices") as lookup:
            lookup.return_value = {"exists": True, "participant": "ABC-12-3456", "context": "free_living", "devices": ["Mobile_17"]}
            self.view.verify_kit()
            work, success, _failed = submit.call_args.args
            success(work())
            lookup.assert_called_once_with(self.client, "Kit_17", "mobile")
        self.assertEqual(self.context.values["participant"].get(), "ABC-12-3456")
        self.assertEqual(self.view.vars["mobile"].get(), "Mobile_17")
        self.assertEqual(self.view.kit_label["style"], "Mobile.Found.TLabel")
        self.assertFalse(self.view.progress_running)

    def test_late_lookup_is_ignored_and_close_discards_results(self):
        self.client.offline_session = None
        self.client.session = SimpleNamespace(access_token="jwt")
        self.view.vars["kit"].set("Kit_17")
        with patch.object(self.view, "submit") as submit:
            self.view.verify_kit()
            self.view.vars["kit"].set("Kit_18")
            submit.call_args.args[1]({"exists": True, "participant": "ABC-12-3456", "context": "free_living", "devices": ["Mobile_17"]})
        self.assertEqual(self.view.vars["participant"].get(), "")
        self.view.outer.destroy()
        callback = MagicMock()
        self.view.events.put((callback, None))
        self.view.poll()
        callback.assert_not_called()


class SmartphoneApiTests(unittest.TestCase):
    @patch("api.client.requests.request")
    def test_smartphone_lookup_sends_jwt_and_ignores_watch_names(self, request):
        client = ApiClient("https://example.test")
        client.session = SimpleNamespace(access_token="jwt")
        response = MagicMock(status_code=200)
        response.json.return_value = {"exists": True, "smartphones": [{"name": "Mobile_17"}],
                                      "smartwatches": [{"name": "Watch_10"}]}
        request.return_value = response
        self.assertEqual(check_kit_devices(client, "Kit_17", "mobile")["devices"], ["Mobile_17"])
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer jwt")
