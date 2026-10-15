"""Wire protocol shared by Python reader and server (documented for ESP32)."""
import hashlib
import hmac
import json
import secrets
import time
import uuid


def valid_uuid(value):
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def valid_secret(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def request_signature(secret: str, method: str, target: str, timestamp: str, nonce: str, body: bytes) -> str:
    message = "\n".join((method.upper(), target, timestamp, nonce, digest(body)))
    return hmac.new(bytes.fromhex(secret), message.encode("utf-8"), hashlib.sha256).hexdigest()


def response_signature(secret: str, nonce: str, status: int, body: bytes) -> str:
    message = f"{nonce}\n{status}\n{digest(body)}"
    return hmac.new(bytes.fromhex(secret), message.encode("utf-8"), hashlib.sha256).hexdigest()


def signed_headers(device_uuid: str, secret: str, method: str, target: str, body: bytes) -> dict:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    return {
        "X-Device-Id": device_uuid,
        "X-Device-Timestamp": timestamp,
        "X-Device-Nonce": nonce,
        "X-Device-Signature": request_signature(secret, method, target, timestamp, nonce, body),
    }


def verify_response(response, secret: str, nonce: str):
    actual = response.headers.get("X-Device-Response-Signature", "")
    expected = response_signature(secret, nonce, response.status_code, response.content)
    if not hmac.compare_digest(actual, expected):
        raise ValueError("Invalid device response signature")


def signed_request(client, method: str, url: str, device_uuid: str, secret: str, payload=None, **kwargs):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if payload is not None else b""
    request = client.build_request(method, url, content=body, headers={"Content-Type": "application/json", **kwargs.pop("headers", {})}, **kwargs)
    target = request.url.raw_path.decode("ascii")
    request.headers.update(signed_headers(device_uuid, secret, method, target, body))
    response = client.send(request)
    verify_response(response, secret, request.headers["X-Device-Nonce"])
    return response
