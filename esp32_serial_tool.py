"""USB Serial maintenance window for the CVTA ESP32 reader."""

import codecs
import sys
import time
from collections import deque

from PySide6.QtCore import QIODeviceBase, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSlider, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from esp32_serial_protocol import (
    calibration_command, encode_command, name_command,
    needs_destructive_confirmation, parse_display, server_command,
    visible_command, wifi_command,
)


class OffsetSlider(QSlider):
    """Move one offset unit per wheel notch; arrow keys use QSlider's step."""

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setRange(0, 128)
        self.setSingleStep(1)
        self.setPageStep(10)
        self.setTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._wheel_remainder = 0

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta:
            self._wheel_remainder += delta
            steps = int(self._wheel_remainder / 120)
            self._wheel_remainder -= steps * 120
        else:
            pixel_delta = event.pixelDelta().y()
            steps = (pixel_delta > 0) - (pixel_delta < 0)
        if steps:
            self.setValue(self.value() + steps)
        event.accept()


class Esp32SerialWindow(QMainWindow):
    def __init__(self, serial=None, port_provider=None):
        super().__init__()
        self.serial = serial if serial is not None else QSerialPort(self)
        self.port_provider = port_provider or QSerialPortInfo.availablePorts
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._pending_text = ""
        self._geometry_generation = 0
        self._display_queries = deque()
        self._geometry_known = False
        self._last_sent_orientation = None
        self._last_sent_offsets = None
        self._initial_display_timer = QTimer(self)
        self._initial_display_timer.setSingleShot(True)
        self._initial_display_timer.timeout.connect(self._query_initial_display)
        self._display_refresh_timer = QTimer(self)
        self._display_refresh_timer.setSingleShot(True)
        self._display_refresh_timer.setInterval(200)
        self._display_refresh_timer.timeout.connect(self._finish_geometry_edit)
        self._periodic_display_timer = QTimer(self)
        self._periodic_display_timer.setInterval(5000)
        self._periodic_display_timer.timeout.connect(self._periodic_display)
        self.setWindowTitle("CVTA ESP32 USB 設定工具")
        self.resize(900, 720)
        self.setMinimumSize(600, 480)
        self._make_ui()
        self.serial.readyRead.connect(self._read_serial)
        self.serial.errorOccurred.connect(self._serial_error)
        self.refresh_ports()
        self._reset_geometry()
        self._set_connected(False)

    def _make_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)

        connection = QHBoxLayout()
        connection.addWidget(QLabel("COM 埠"))
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumWidth(170)
        self.port_combo.setAccessibleName("COM 埠")
        connection.addWidget(self.port_combo, 1)
        self.refresh_button = QPushButton("重新掃描")
        self.refresh_button.clicked.connect(self.refresh_ports)
        connection.addWidget(self.refresh_button)
        self.connect_button = QPushButton("連接")
        self.connect_button.clicked.connect(self.toggle_connection)
        connection.addWidget(self.connect_button)
        self.connection_label = QLabel("未連接 · 115200 baud")
        connection.addWidget(self.connection_label)
        layout.addLayout(connection)
        note = QLabel("開啟 COM 埠可能使 ESP32 重新啟動；請等待下方出現開機訊息後再操作。")
        note.setWordWrap(True)
        layout.addWidget(note)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._scroll_page(self._lcd_page()), "LCD 校正")
        self.tabs.addTab(self._scroll_page(self._settings_page()), "裝置設定")
        self.tabs.addTab(self._scroll_page(self._diagnostics_page()), "診斷與進階")
        splitter.addWidget(self.tabs)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Serial 回覆與狀態"))
        heading.addStretch()
        clear_button = QPushButton("清除畫面")
        clear_button.clicked.connect(self._clear_log)
        heading.addWidget(clear_button)
        log_layout.addLayout(heading)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setAccessibleName("Serial 回覆與狀態")
        self.log.document().setMaximumBlockCount(1200)
        log_layout.addWidget(self.log)
        splitter.addWidget(log_panel)
        splitter.setSizes([460, 200])
        layout.addWidget(splitter, 1)

    @staticmethod
    def _scroll_page(content):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(content)
        return area

    def _lcd_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        display_group = QGroupBox("顯示器目前設定")
        display_layout = QVBoxLayout(display_group)
        self.display_label = QLabel("尚未從裝置讀取")
        display_label_font = self.display_label.font()
        display_label_font.setPointSize(display_label_font.pointSize() + 2)
        self.display_label.setFont(display_label_font)
        display_layout.addWidget(self.display_label)
        row = QHBoxLayout()
        row.addWidget(self._command_button("讀取 display", "display"))
        row.addWidget(self._command_button("顯示定位框", "frame"))
        row.addWidget(self._command_button("關閉定位框", "frame off"))
        row.addStretch()
        display_layout.addLayout(row)
        layout.addWidget(display_group)

        self.edit_group = QGroupBox("校正方向與偏移")
        form = QFormLayout(self.edit_group)
        self.orientation_combo = QComboBox()
        for label in ("0 · 正常", "1 · 左右鏡像", "2 · 上下鏡像", "3 · 旋轉 180°"):
            self.orientation_combo.addItem(label)
        self.orientation_combo.currentIndexChanged.connect(self._orientation_changed)
        form.addRow("方向", self.orientation_combo)
        self.column_slider = OffsetSlider()
        self.column_slider.setAccessibleName("水平偏移 column")
        self.column_value = QLabel("0")
        self.column_value.setMinimumWidth(32)
        column_row = QHBoxLayout()
        column_row.addWidget(self.column_slider, 1)
        column_row.addWidget(self.column_value)
        form.addRow("水平偏移 column", column_row)
        self.row_slider = OffsetSlider()
        self.row_slider.setAccessibleName("垂直偏移 row")
        self.row_value = QLabel("0")
        self.row_value.setMinimumWidth(32)
        row_layout = QHBoxLayout()
        row_layout.addWidget(self.row_slider, 1)
        row_layout.addWidget(self.row_value)
        form.addRow("垂直偏移 row", row_layout)
        self.column_slider.valueChanged.connect(self._offset_changed)
        self.row_slider.valueChanged.connect(self._offset_changed)
        layout.addWidget(self.edit_group)
        hint = QLabel("方向、滑桿拖動、方向鍵及滾輪會立即送出設定。定位框應完整顯示四邊與四色角標，且 TOP 位於上方；重啟後再讀取確認。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        return page

    def _settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        network = QGroupBox("Wi-Fi")
        form = QFormLayout(network)
        self.ssid_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("SSID", self.ssid_edit)
        form.addRow("密碼", self.password_edit)
        wifi_button = QPushButton("儲存 Wi-Fi")
        wifi_button.clicked.connect(self._save_wifi)
        form.addRow("", wifi_button)
        layout.addWidget(network)

        server = QGroupBox("伺服器")
        form = QFormLayout(server)
        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("http://192.168.1.10:16688")
        form.addRow("位址", self.server_edit)
        server_button = QPushButton("儲存伺服器")
        server_button.clicked.connect(self._save_server)
        form.addRow("", server_button)
        server_note = QLabel("更換位址會讓裝置重新檢查註冊與核准；請在後台確認 UUID 與核准狀態。")
        server_note.setWordWrap(True)
        form.addRow("", server_note)
        layout.addWidget(server)

        identity = QGroupBox("名稱與卡號校正")
        form = QFormLayout(identity)
        self.name_edit = QLineEdit()
        form.addRow("設備名稱", self.name_edit)
        name_button = QPushButton("儲存名稱")
        name_button.clicked.connect(self._save_name)
        form.addRow("", name_button)
        self.uid_edit = QLineEdit()
        self.uid_edit.setPlaceholderText("既有卡片 UID：8、14 或 20 位十六進位")
        form.addRow("既有 UID", self.uid_edit)
        calibrate_button = QPushButton("開始 UID 校正")
        calibrate_button.clicked.connect(self._calibrate)
        form.addRow("", calibrate_button)
        uid_note = QLabel("送出後 60 秒內刷同一張既有卡；只有裝置顯示 UID MATCH 才可開始正式打卡。")
        uid_note.setWordWrap(True)
        form.addRow("", uid_note)
        layout.addWidget(identity)
        layout.addStretch()
        return page

    def _diagnostics_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("常用診斷")
        row = QHBoxLayout(group)
        for command in ("help", "status", "queue", "bad", "poll", "selftest"):
            row.addWidget(self._command_button(command, command))
        row.addStretch()
        layout.addWidget(group)
        advanced = QGroupBox("進階指令")
        form = QFormLayout(advanced)
        self.raw_edit = QLineEdit()
        self.raw_edit.setPlaceholderText("輸入一行既有韌體指令；按 Enter 送出")
        self.raw_edit.returnPressed.connect(self._send_raw)
        form.addRow("指令", self.raw_edit)
        send_button = QPushButton("送出指令")
        send_button.clicked.connect(self._send_raw)
        form.addRow("", send_button)
        raw_note = QLabel("Wi-Fi 密碼請使用「裝置設定」中的遮蔽欄位。初始化儲存或刪除壞事件前會再次確認。")
        raw_note.setWordWrap(True)
        form.addRow("", raw_note)
        layout.addWidget(advanced)
        layout.addStretch()
        return page

    def _command_button(self, label, command):
        button = QPushButton(label)
        button.clicked.connect(lambda: self.send_command(command))
        return button

    def refresh_ports(self):
        current = self.port_combo.currentText().strip()
        self.port_combo.clear()
        for info in self.port_provider():
            self.port_combo.addItem(f"{info.portName()} · {info.description()}", info.portName())
        if current:
            port = current.split(" · ", 1)[0]
            matches = self.port_combo.findData(port)
            if matches >= 0:
                self.port_combo.setCurrentIndex(matches)
            else:
                self.port_combo.setEditText(port)

    def toggle_connection(self):
        if self.serial.isOpen():
            self.disconnect_port()
            return
        port = self.port_combo.currentData() if self.port_combo.currentIndex() >= 0 else None
        if not port or self.port_combo.currentText().split(" · ", 1)[0] != port:
            port = self.port_combo.currentText().strip().split(" · ", 1)[0]
        if not port:
            QMessageBox.warning(self, "尚未選擇 COM 埠", "請選擇或輸入 COM 埠名稱。")
            return
        self.serial.setPortName(port)
        self.serial.setBaudRate(115200)
        self.serial.setDataBits(QSerialPort.DataBits.Data8)
        self.serial.setParity(QSerialPort.Parity.NoParity)
        self.serial.setStopBits(QSerialPort.StopBits.OneStop)
        self.serial.setFlowControl(QSerialPort.FlowControl.NoFlowControl)
        if not self.serial.open(QIODeviceBase.OpenModeFlag.ReadWrite):
            QMessageBox.warning(self, "無法連接", f"無法開啟 {port}：{self.serial.errorString()}\n請檢查 USB、COM 埠及其他序列監控器。")
            self._set_connected(False)
            return
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._pending_text = ""
        self._reset_geometry()
        self._set_connected(True)
        self._append(f"[工具] 已連接 {port} · 115200 baud；等待裝置啟動。")
        self._initial_display_timer.start(1500)
        self._periodic_display_timer.start()

    def disconnect_port(self, reason="已中斷連線"):
        if self.serial.isOpen():
            self.serial.close()
        if self._pending_text:
            self._append(self._pending_text)
        self._pending_text = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._reset_geometry()
        self._set_connected(False)
        self._append(f"[工具] {reason}。")

    def _reset_geometry(self):
        self._initial_display_timer.stop()
        self._display_refresh_timer.stop()
        self._periodic_display_timer.stop()
        self._display_queries.clear()
        self._geometry_generation += 1
        self._geometry_known = False
        self._last_sent_orientation = None
        self._last_sent_offsets = None
        self.edit_group.setEnabled(False)
        self.display_label.setText("尚未從裝置讀取")

    def _query_initial_display(self):
        if self.serial.isOpen() and not self._geometry_known:
            self.send_command("display")

    def _periodic_display(self):
        if not self.serial.isOpen() or self._display_refresh_timer.isActive():
            return
        self._expire_display_queries()
        if not self._display_queries:
            self.send_command("display")

    def _expire_display_queries(self):
        now = time.monotonic()
        while self._display_queries and now - self._display_queries[0][1] > 10:
            self._display_queries.popleft()

    def _orientation_changed(self, index):
        if self._geometry_known:
            self._geometry_changed("orientation")

    def _offset_changed(self):
        self.column_value.setText(str(self.column_slider.value()))
        self.row_value.setText(str(self.row_slider.value()))
        if self._geometry_known:
            self._geometry_changed("offsets")

    def _geometry_changed(self, kind):
        self._geometry_generation += 1
        self.display_label.setText("等待裝置確認…")
        if not self._display_refresh_timer.isActive():
            if kind == "orientation":
                self._send_orientation()
            else:
                self._send_offsets()
        if self.serial.isOpen():
            self._display_refresh_timer.start()

    def _send_orientation(self):
        orientation = self.orientation_combo.currentIndex()
        if orientation == self._last_sent_orientation:
            return True
        if self.send_command(f"m {orientation}"):
            self._last_sent_orientation = orientation
            return True
        return False

    def _send_offsets(self):
        offsets = self.column_slider.value(), self.row_slider.value()
        if offsets == self._last_sent_offsets:
            return True
        if self.send_command(f"o {offsets[0]} {offsets[1]}"):
            self._last_sent_offsets = offsets
            return True
        return False

    def _finish_geometry_edit(self):
        if not self.serial.isOpen():
            return
        if self._geometry_known and not (self._send_orientation() and self._send_offsets()):
            return
        self.send_command("display")

    def _apply_hardware_geometry(self, geometry):
        orientation, column, row = geometry
        with (QSignalBlocker(self.orientation_combo),
              QSignalBlocker(self.column_slider), QSignalBlocker(self.row_slider)):
            self.orientation_combo.setCurrentIndex(orientation)
            self.column_slider.setValue(column)
            self.row_slider.setValue(row)
        self.column_value.setText(str(column))
        self.row_value.setText(str(row))
        self.display_label.setText(f"方向 {orientation} · 水平 {column} · 垂直 {row}")
        self._geometry_known = True
        self._last_sent_orientation = orientation
        self._last_sent_offsets = column, row
        self.edit_group.setEnabled(True)
        self._initial_display_timer.stop()

    def _set_connected(self, connected):
        self.connect_button.setText("斷線" if connected else "連接")
        self.connection_label.setText(
            f"已連接 · {self.serial.portName()} · 115200 baud" if connected else "未連接 · 115200 baud")

    def _serial_error(self, error):
        if error == QSerialPort.SerialPortError.NoError or not self.serial.isOpen():
            return
        if error in (QSerialPort.SerialPortError.ResourceError,
                     QSerialPort.SerialPortError.DeviceNotFoundError,
                     QSerialPort.SerialPortError.PermissionError):
            message = self.serial.errorString()
            self.disconnect_port(f"連線中斷：{message}")

    def _read_serial(self):
        chunk = bytes(self.serial.readAll())
        if not chunk:
            return
        self._pending_text += self._decoder.decode(chunk)
        while "\n" in self._pending_text:
            line, self._pending_text = self._pending_text.split("\n", 1)
            line = line.rstrip("\r")
            self._append(line)
            if line.startswith("Device UUID:") and not self._geometry_known:
                self._display_queries.clear()
                self._initial_display_timer.stop()
                self._query_initial_display()
            geometry = parse_display(line)
            if geometry:
                self._expire_display_queries()
                generation = (self._display_queries.popleft()
                              if self._display_queries else (self._geometry_generation, 0))[0]
                if (generation == self._geometry_generation and
                        not self._display_refresh_timer.isActive()):
                    self._apply_hardware_geometry(geometry)
        if len(self._pending_text) > 8192:
            self._append(self._pending_text[:8192] + " [輸出過長，已截斷]")
            self._pending_text = ""

    def send_command(self, command):
        if not self.serial.isOpen():
            QMessageBox.warning(self, "尚未連接", "請先連接 ESP32 的 COM 埠。")
            return False
        try:
            payload = encode_command(command)
        except ValueError as exc:
            QMessageBox.warning(self, "指令錯誤", str(exc))
            return False
        if needs_destructive_confirmation(command):
            if command == "init-storage NEW":
                detail = "這會在儲存區無法掛載時初始化 LittleFS。請先確認離線事件與現場資料風險。"
            else:
                detail = "這會永久刪除指定的壞事件，無法由此工具復原。"
            answer = QMessageBox.question(self, "確認裝置儲存操作", f"{detail}\n\n確定送出 {command}？")
            if answer != QMessageBox.StandardButton.Yes:
                return False
        written = self.serial.write(payload)
        if written != len(payload):
            self.disconnect_port("指令未完整寫入，請重新連接並確認裝置狀態")
            return False
        self._append(f"> {visible_command(command)}")
        if command == "display":
            self._expire_display_queries()
            self._display_queries.append((self._geometry_generation, time.monotonic()))
        return True

    def _send_raw(self):
        command = self.raw_edit.text().strip()
        if command.startswith("wifi "):
            QMessageBox.warning(self, "請使用遮蔽欄位", "Wi-Fi 設定請使用「裝置設定」頁面的密碼欄位。")
            return
        if self.send_command(command):
            self.raw_edit.clear()
            if command.startswith(("m ", "o ")):
                self._geometry_generation += 1
                self._geometry_known = False
                self.edit_group.setEnabled(False)
                self.display_label.setText("等待裝置確認…")
                self._display_refresh_timer.start()

    def _save_wifi(self):
        try:
            command = wifi_command(self.ssid_edit.text(), self.password_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Wi-Fi 設定錯誤", str(exc))
            return
        if self.send_command(command):
            self.password_edit.clear()

    def _save_server(self):
        try:
            command = server_command(self.server_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "伺服器位址錯誤", str(exc))
            return
        self.send_command(command)

    def _save_name(self):
        try:
            command = name_command(self.name_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "設備名稱錯誤", str(exc))
            return
        self.send_command(command)

    def _calibrate(self):
        try:
            command = calibration_command(self.uid_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "UID 錯誤", str(exc))
            return
        self.send_command(command)

    def _append(self, line):
        self.log.appendPlainText(line)

    def _clear_log(self):
        self.log.clear()

    def closeEvent(self, event):
        self._initial_display_timer.stop()
        self._display_refresh_timer.stop()
        self._periodic_display_timer.stop()
        if self.serial.isOpen():
            self.serial.close()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = Esp32SerialWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
