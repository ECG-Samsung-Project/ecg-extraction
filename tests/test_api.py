import unittest
from unittest.mock import MagicMock, patch

import requests

from api import ApiClient, ApiError, AuthenticationError
from api.client import USER_AGENT


LOGIN = {
    "access_token": "access-secret", "refresh_token": "refresh-secret",
    "token_type": "bearer", "user_id": "123", "username": "tester",
    "full_name": "Test User", "role": "user",
}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = ApiClient("https://example.test")
        self.patcher = patch("api.client.requests.request")
        self.request = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.response = MagicMock(status_code=200)
        self.response.json.return_value = LOGIN.copy()
        self.request.return_value = self.response

    def test_login_and_authenticated_request(self):
        session = self.client.login(" Téster42+@! ", " Páss42!@#$%&* ")
        self.assertEqual(session.user.username, "tester")
        self.assertNotIn("access-secret", repr(session))
        self.assertNotIn("refresh-secret", repr(session))
        self.request.assert_called_once_with(
            "POST", "https://example.test/api/v1/auth/login",
            json={"username": " Téster42+@! ", "password": " Páss42!@#$%&* "},
            headers={"Accept": "*/*", "Content-Type": "application/json",
                     "User-Agent": USER_AGENT}, timeout=(5, 20),
            allow_redirects=False,
        )
        self.client.request_json("GET", "/api/v1/example")
        self.assertEqual(self.request.call_args.kwargs["headers"]["Authorization"],
                         "Bearer access-secret")

    def test_empty_credentials_do_not_send(self):
        for username, password in [("", "secret"), ("tester", "")]:
            with self.assertRaises(ApiError):
                self.client.login(username, password)
        self.request.assert_not_called()

    def test_offline_mode_has_no_tokens_and_does_not_send_requests(self):
        self.client.login("tester", "secret")
        self.request.reset_mock()
        session = self.client.enter_offline("Operator Name")
        self.assertEqual(session.operator_name, "Operator Name")
        self.assertIsNone(self.client.session)
        with self.assertRaises(AuthenticationError):
            self.client.request_json("GET", "/api/v1/example")
        self.request.assert_not_called()
        self.client.login("tester", "secret")
        self.assertIsNone(self.client.offline_session)

    def test_offline_requires_operator_name(self):
        with self.assertRaises(ApiError):
            self.client.enter_offline("   ")
        self.assertIsNone(self.client.offline_session)

    def test_403_includes_detail_without_credentials(self):
        self.response.status_code = 403
        self.response.json.return_value = {"detail": "Blocked tester with secret"}
        with self.assertRaises(ApiError) as caught:
            self.client.login("tester", "secret")
        self.assertEqual(caught.exception.status, 403)
        self.assertIn("Blocked", str(caught.exception))
        self.assertNotIn("tester", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        self.assertIsNone(self.client.offline_session)

    def test_errors_never_authenticate_and_allow_retry(self):
        for code in (401, 403, 429, 500, 302):
            with self.subTest(code=code):
                self.response.status_code = code
                with self.assertRaises(ApiError):
                    self.client.login("tester", "secret")
                self.assertIsNone(self.client.session)
        self.response.status_code = 200
        self.client.login("tester", "secret")
        self.assertIsNotNone(self.client.session)

    def test_malformed_responses(self):
        for data in (None, [], {}, {**LOGIN, "access_token": ""},
                     {**LOGIN, "user_id": 123}, {**LOGIN, "token_type": "basic"}):
            with self.subTest(data=data):
                self.response.json.return_value = data
                with self.assertRaises(ApiError):
                    self.client.login("tester", "secret")
                self.assertIsNone(self.client.session)
        self.response.json.side_effect = ValueError("raw response")
        with self.assertRaises(ApiError):
            self.client.login("tester", "secret")

    def test_transport_errors_are_safe(self):
        for error in (requests.Timeout("secret"), requests.ConnectionError("secret")):
            self.request.side_effect = error
            with self.assertRaises(ApiError) as caught:
                self.client.login("tester", "secret")
            self.assertNotIn("secret", str(caught.exception))

    def test_expired_session_is_cleared(self):
        self.client.login("tester", "secret")
        self.response.status_code = 401
        with self.assertRaises(AuthenticationError):
            self.client.request_json("GET", "/api/v1/example")
        self.assertIsNone(self.client.session)

    def test_requires_session_and_rejects_external_paths(self):
        with self.assertRaises(AuthenticationError):
            self.client.request_json("GET", "/api/v1/example")
        self.client.login("tester", "secret")
        self.request.reset_mock()
        for path in ("https://other.test", "//other.test", "/../other", "/\\other"):
            with self.assertRaises(ValueError):
                self.client.request_json("GET", path)
        self.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
