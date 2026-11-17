import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api import ApiError, AuthSession, OfflineSession, User
from auth.frontend import create_login_frame


class LoginUiTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch("auth.frontend.ttk"), patch("auth.frontend.tk.StringVar"),
                        patch("auth.frontend.threading.Thread")]
        self.ttk, self.string_var, self.thread = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.username, self.password = MagicMock(), MagicMock()
        self.username.get.return_value = "tester"
        self.password.get.return_value = "secret"
        self.ttk.Entry.side_effect = [self.username, self.password]
        self.client, self.success = MagicMock(), MagicMock()
        self.frame = create_login_frame(MagicMock(), self.client, self.success)
        self.submit = self.ttk.Button.call_args.kwargs["command"]
        self.offline = next(call.kwargs["command"] for call in self.ttk.Button.call_args_list
                            if call.kwargs.get("text") == "Continuar sem login (modo offline)")

    @patch("auth.frontend.simpledialog.askstring")
    def test_offline_is_explicit_and_blocked_during_login(self, ask):
        ask.return_value = "Operator"
        self.client.enter_offline.return_value = OfflineSession("Operator")
        self.offline()
        self.client.enter_offline.assert_called_once_with("Operator")
        self.success.assert_called_once_with(self.client.enter_offline.return_value)
        self.password.delete.assert_called_once()
        self.client.login.assert_not_called()
        ask.reset_mock()
        self.submit()
        self.offline()
        ask.assert_not_called()

    @patch("auth.frontend.simpledialog.askstring", return_value=None)
    def test_cancel_offline_stays_on_login(self, ask):
        self.offline()
        self.client.enter_offline.assert_not_called()
        self.success.assert_not_called()

    def complete_request(self):
        self.thread.call_args.kwargs["target"]()
        self.frame.after.call_args.args[1]()

    def test_blank_fields_and_duplicate_submissions(self):
        self.username.get.return_value = ""
        self.submit()
        self.thread.assert_not_called()
        self.username.get.return_value = " Téster42+@! "
        self.password.get.return_value = " Páss42!@#$%&* "
        self.submit()
        self.submit()
        self.thread.assert_called_once()
        self.password.configure.assert_called_with(state="disabled")
        self.complete_request()
        self.client.login.assert_called_once_with(" Téster42+@! ", " Páss42!@#$%&* ")

    def test_failure_clears_password_and_allows_retry(self):
        self.client.login.side_effect = ApiError("Falha")
        self.submit()
        self.complete_request()
        self.success.assert_not_called()
        self.password.delete.assert_called_once()
        self.password.configure.assert_called_with(state="normal")
        self.client.login.side_effect = None
        self.client.login.return_value = AuthSession("a", "r", "bearer", User("1", "u", "U", "user"))
        self.submit()
        self.complete_request()
        self.success.assert_called_once_with(self.client.login.return_value)

    def test_close_cancels_poll_and_discards_late_result(self):
        self.submit()
        poll = self.frame.after.call_args.args[1]
        destroy = self.frame.bind.call_args.args[1]
        destroy(SimpleNamespace(widget=self.frame))
        self.frame.after_cancel.assert_called_once()
        self.thread.call_args.kwargs["target"]()
        poll()
        self.success.assert_not_called()
        self.password.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
