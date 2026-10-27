import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtSerialPort import QSerialPort
from PySide6.QtWidgets import QApplication, QMessageBox

from esp32_serial_protocol import (
    calibration_command, encode_command, name_command, needs_destructive_confirmation,
    parse_display, server_command, visible_command, wifi_command,
)
from esp32_serial_tool import Esp32SerialWindow


class FakeSerial(QObject):
    readyRead = Signal()
    errorOccurred = Signal(object)

    def __init__(self):
        super().__init__()
        self.opened = False
        self.port = ""
        self.incoming = b""
        self.writes = []
        self.open_result = True

    def setPortName(self, value): self.port = value
    def portName(self): return self.port
    def setBaudRate(self, value): self.baud = value
    def setDataBits(self, value): pass
    def setParity(self, value): pass
    def setStopBits(self, value): pass
    def setFlowControl(self, value): pass
    def isOpen(self): return self.opened
    def open(self, mode):
        self.opened = self.open_result
        return self.opened
    def close(self): self.opened = False
    def errorString(self): return "test disconnection"
    def write(self, payload):
        self.writes.append(payload)
        return len(payload)
    def readAll(self):
        payload, self.incoming = self.incoming, b""
        return payload
    def feed(self, payload):
        self.incoming += payload
        self.readyRead.emit()


class ProtocolTests(unittest.TestCase):
    def test_command_encoding_and_validation(self):
        self.assertEqual(encode_command("display"), b"display\n")
        self.assertEqual(len(encode_command("x" * 220)), 221)
        for value in ("", "x\ny", "x\ry", "x" * 221, "界" * 74):
            with self.subTest(value=value[:10]), self.assertRaises(ValueError):
                encode_command(value)

    def test_form_commands(self):
        self.assertEqual(wifi_command("Office", "two words"), "wifi Office two words")
        self.assertEqual(server_command("http://reader.local:16688/"),
                         "server http://reader.local:16688")
        self.assertEqual(name_command("讀卡機"), "name 讀卡機")
        self.assertEqual(calibration_command("a1b2c3d4"), "calibrate A1B2C3D4")
        for value in ("", "Office WiFi"):
            with self.assertRaises(ValueError): wifi_command(value, "secret")
        for value in ("https://host:16688", "http://host:16688/path", "http://host",
                      "http://host:16688?", "http://[invalid:16688"):
            with self.assertRaises(ValueError): server_command(value)
        with self.assertRaises(ValueError): calibration_command("A1B2")

    def test_display_and_confirmation(self):
        self.assertEqual(parse_display("Display: m 3, o 2 3 (0=normal)"), (3, 2, 3))
        self.assertIsNone(parse_display("[status] READY"))
        self.assertIsNone(parse_display("Display: m 3, o 129 3"))
        self.assertEqual(visible_command("wifi Office secret words"), "wifi Office ******")
        self.assertTrue(needs_destructive_confirmation("init-storage NEW"))
        self.assertTrue(needs_destructive_confirmation("discard-bad 123"))
        self.assertFalse(needs_destructive_confirmation("queue"))


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.serial = FakeSerial()
        self.window = Esp32SerialWindow(serial=self.serial, port_provider=lambda: [])
        self.window.port_combo.setEditText("COM7")

    def tearDown(self):
        self.window.close()

    def test_connect_commands_and_split_output(self):
        self.window.toggle_connection()
        self.assertTrue(self.serial.opened)
        self.assertEqual(self.serial.baud, 115200)
        self.assertTrue(self.window.send_command("m 3", refresh_display=True))
        self.assertEqual(self.serial.writes, [b"m 3\n", b"display\n"])
        self.serial.feed(b"[status] REA")
        self.assertNotIn("[status] READY", self.window.log.toPlainText())
        self.serial.feed(b"DY\nDisplay: m 3, o 2")
        self.serial.feed(b" 3 (0=normal)\n")
        self.assertEqual(self.window.display_label.text(), "方向 3 · 水平 2 · 垂直 3")
        self.assertIn("[status] READY", self.window.log.toPlainText())

    def test_split_utf8_and_failed_open(self):
        self.serial.open_result = False
        with patch.object(QMessageBox, "warning") as warning:
            self.window.toggle_connection()
        warning.assert_called_once()
        self.assertFalse(self.serial.opened)
        self.serial.open_result = True
        self.window.toggle_connection()
        encoded = "已保存\n".encode("utf-8")
        self.serial.feed(encoded[:2])
        self.serial.feed(encoded[2:])
        self.assertIn("已保存", self.window.log.toPlainText())

    def test_wifi_is_masked_and_disconnection_is_visible(self):
        self.window.toggle_connection()
        self.window.ssid_edit.setText("Office")
        self.window.password_edit.setText("private pass")
        self.window._save_wifi()
        self.assertEqual(self.serial.writes[-1], b"wifi Office private pass\n")
        self.assertNotIn("private pass", self.window.log.toPlainText())
        self.assertEqual(self.window.password_edit.text(), "")
        self.serial.errorOccurred.emit(QSerialPort.SerialPortError.ResourceError)
        self.assertFalse(self.serial.opened)
        self.assertIn("連線中斷", self.window.log.toPlainText())

    def test_high_risk_command_requires_confirmation(self):
        self.window.toggle_connection()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.window.send_command("discard-bad 42"))
        self.assertEqual(self.serial.writes, [])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(self.window.send_command("discard-bad 42"))
        self.assertEqual(self.serial.writes, [b"discard-bad 42\n"])

    def test_raw_wifi_is_rejected(self):
        self.window.toggle_connection()
        self.window.raw_edit.setText("wifi Office private")
        with patch.object(QMessageBox, "warning"):
            self.window._send_raw()
        self.assertEqual(self.serial.writes, [])


if __name__ == "__main__":
    unittest.main()
