"""Validation and display helpers for the ESP32 line-oriented USB console."""

import re
from urllib.parse import urlsplit


MAX_COMMAND_BYTES = 220
DISPLAY_RE = re.compile(r"^Display: m ([0-3]), o (\d{1,3}) (\d{1,3})\b")
UID_RE = re.compile(r"(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{14}|[0-9a-fA-F]{20})\Z")


def encode_command(command: str) -> bytes:
    """Encode one firmware command, including its required LF terminator."""
    if not command or not command.strip():
        raise ValueError("請輸入指令。")
    if "\r" in command or "\n" in command or "\x00" in command:
        raise ValueError("指令只能佔一行，且不能包含控制字元。")
    payload = command.encode("utf-8")
    if len(payload) > MAX_COMMAND_BYTES:
        raise ValueError("指令超過韌體的 220 位元組上限。")
    return payload + b"\n"


def wifi_command(ssid: str, password: str) -> str:
    if not ssid or any(ch.isspace() for ch in ssid):
        raise ValueError("Wi-Fi 名稱不可空白或包含空白字元。")
    if not password:
        raise ValueError("請輸入 Wi-Fi 密碼。")
    command = f"wifi {ssid} {password}"
    encode_command(command)
    return command


def server_command(address: str) -> str:
    address = address.strip().removesuffix("/")
    try:
        parts = urlsplit(address)
        port = parts.port
    except ValueError:
        raise ValueError("請輸入不含路徑的 http://主機:埠 位址。") from None
    if (parts.scheme != "http" or not parts.hostname or port is None or
            not 1 <= port <= 65535 or parts.path or parts.query or parts.fragment or
            parts.username or parts.password or
            any(ch.isspace() for ch in address) or
            any(char in address for char in "@?#")):
        raise ValueError("請輸入不含路徑的 http://主機:埠 位址。")
    command = f"server {address}"
    encode_command(command)
    return command


def name_command(name: str) -> str:
    name = name.strip()
    if not name or len(name.encode("utf-8")) > 100:
        raise ValueError("設備名稱須為 1–100 位元組。")
    command = f"name {name}"
    encode_command(command)
    return command


def calibration_command(uid: str) -> str:
    uid = uid.strip()
    if not UID_RE.fullmatch(uid):
        raise ValueError("既有 UID 須為 8、14 或 20 位十六進位字元。")
    return f"calibrate {uid.upper()}"


def visible_command(command: str) -> str:
    if command.startswith("wifi "):
        fields = command.split(" ", 2)
        return f"wifi {fields[1]} ******" if len(fields) == 3 else "wifi ******"
    return command


def needs_destructive_confirmation(command: str) -> bool:
    return command == "init-storage NEW" or command.startswith("discard-bad ")


def parse_display(line: str) -> tuple[int, int, int] | None:
    match = DISPLAY_RE.match(line)
    if not match:
        return None
    values = tuple(map(int, match.groups()))
    return values if values[1] <= 128 and values[2] <= 128 else None
