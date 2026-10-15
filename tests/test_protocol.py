import unittest

from device_protocol import request_signature, response_signature, signed_headers


class ProtocolTests(unittest.TestCase):
    def test_signature_covers_request_and_response(self):
        secret = "ab" * 32
        body = b'{"uid":"123"}'
        headers = signed_headers("00000000-0000-4000-8000-000000000000", secret,
                                 "POST", "/api/v1/punch", body)
        signature = headers["X-Device-Signature"]
        self.assertEqual(signature, request_signature(secret, "POST", "/api/v1/punch",
                         headers["X-Device-Timestamp"], headers["X-Device-Nonce"], body))
        self.assertNotEqual(signature, request_signature(secret, "POST", "/api/v1/punch",
                            headers["X-Device-Timestamp"], headers["X-Device-Nonce"], b'{"uid":"456"}'))
        self.assertNotEqual(response_signature(secret, headers["X-Device-Nonce"], 200, b"{}"),
                            response_signature(secret, headers["X-Device-Nonce"], 403, b"{}"))


if __name__ == "__main__":
    unittest.main()
