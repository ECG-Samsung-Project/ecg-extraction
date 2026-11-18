import unittest
from unittest.mock import MagicMock, patch

import main


class NavigationTests(unittest.TestCase):
    def test_offline_opens_local_tabs_without_constructing_upload(self):
        with (patch.object(main.tk, "Tk") as root_factory,
              patch.object(main, "ApiClient") as client_factory,
              patch.object(main, "create_login_frame") as login_factory,
              patch.object(main, "ttk") as ttk,
              patch.object(main, "create_watch_frame") as watch,
              patch.object(main, "create_mobile_frame") as mobile,
              patch.object(main, "create_server_sync_frame") as sync):
            client = client_factory.return_value
            client.session = None
            session = main.OfflineSession("Operator")
            client.offline_session = session

            def event_loop():
                callback = login_factory.call_args.args[2]
                callback(session)
                watch.assert_called_once()
                mobile.assert_called_once()
                sync.assert_not_called()
                ttk.Notebook.return_value.add.assert_any_call(
                    ttk.Frame.return_value, text="Enviar ao Servidor", state="disabled")

            root_factory.return_value.mainloop.side_effect = event_loop
            main.run_app()

    def test_tabs_are_created_only_after_login_and_only_once(self):
        with (patch.object(main.tk, "Tk") as root_factory,
              patch.object(main, "ApiClient") as client_factory,
              patch.object(main, "create_login_frame") as login_factory,
              patch.object(main.ttk, "Notebook") as notebook_factory,
              patch.object(main.ttk, "Label"),
              patch.object(main, "create_watch_frame") as watch,
              patch.object(main, "create_mobile_frame") as mobile,
              patch.object(main, "create_server_sync_frame") as sync):
            client = client_factory.return_value
            client.session = None

            def event_loop():
                callback = login_factory.call_args.args[2]
                notebook_factory.assert_not_called()
                for factory in (watch, mobile, sync):
                    factory.assert_not_called()
                callback(None)
                notebook_factory.assert_not_called()
                client.session = MagicMock()
                callback(client.session)
                callback(client.session)
                notebook_factory.assert_called_once()
                watch.assert_called_once_with(notebook_factory.return_value, api_client=client)
                for factory in (mobile, sync):
                    factory.assert_called_once_with(notebook_factory.return_value)
                login_factory.return_value.destroy.assert_called_once()
                self.assertEqual(notebook_factory.return_value.add.call_count, 3)

            root_factory.return_value.mainloop.side_effect = event_loop
            main.run_app()


class InterruptionTests(unittest.TestCase):
    @patch.object(main, "_run_application", side_effect=KeyboardInterrupt)
    @patch.object(main.tk, "Tk")
    def test_interrupt_closes_window_without_propagating(self, root_factory, run):
        main.run_app()
        root_factory.return_value.destroy.assert_called_once()
        root_factory.return_value.after_cancel.assert_called_once()

    @patch.object(main.tk, "Tk")
    def test_callback_interrupt_quits_without_error_report(self, root_factory):
        root = root_factory.return_value
        original_report = root.report_callback_exception
        def callback(_root):
            root.report_callback_exception(KeyboardInterrupt, KeyboardInterrupt(), None)
        with patch.object(main, "_run_application", side_effect=callback):
            main.run_app()
        root.quit.assert_called_once()
        root.destroy.assert_called_once()
        original_report.assert_not_called()

    @patch.object(main.tk, "Tk")
    def test_other_callback_errors_are_still_reported(self, root_factory):
        root = root_factory.return_value
        original_report = root.report_callback_exception
        error = RuntimeError("real failure")
        def callback(_root):
            root.report_callback_exception(RuntimeError, error, None)
        with patch.object(main, "_run_application", side_effect=callback):
            main.run_app()
        original_report.assert_called_once_with(RuntimeError, error, None)
        root.quit.assert_not_called()

    @patch.object(main, "_run_application", side_effect=RuntimeError("real failure"))
    @patch.object(main.tk, "Tk")
    def test_other_application_errors_are_not_swallowed(self, root_factory, run):
        with self.assertRaisesRegex(RuntimeError, "real failure"):
            main.run_app()
        root_factory.return_value.destroy.assert_called_once()

    @patch.object(main, "_run_application")
    @patch.object(main.tk, "Tk")
    def test_already_destroyed_window_is_a_normal_exit(self, root_factory, run):
        root_factory.return_value.destroy.side_effect = main.tk.TclError("already destroyed")
        main.run_app()


if __name__ == "__main__":
    unittest.main()
