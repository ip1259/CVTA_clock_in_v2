import logging
from PySide6.QtCore import QObject, Signal, QTimer, Slot, Qt
from pynput import keyboard

logger = logging.getLogger(__name__)


class GlobalCardReader(QObject):
    # 當識別出一串完整的卡號時發送
    card_scanned = Signal(str)
    # pynput 僅傳遞按鍵；緩衝與計時器只在 GUI 執行緒操作。
    _key_pressed = Signal(str, bool)

    def __init__(self, threshold_ms: int = 50):
        super().__init__()
        self.threshold_ms = threshold_ms
        self.key_buffer = []

        # 1. 初始化計時器 (此物件屬於建立它的執行緒，通常是主 GUI 執行緒)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._on_input_finished)

        self._key_pressed.connect(self._record_key, Qt.QueuedConnection)

        self.listener = None
        self._stopped = True

    def start(self):
        self._stopped = False
        # pynput 的 Listener 本質是 Thread，一旦停止就必須重新建立實例
        if self.listener is None or not self.listener.running:
            self.listener = keyboard.Listener(on_press=self._on_press)
            self.listener.daemon = True
            self.listener.start()
        logger.info(f"[Reader] 全域監聽已啟動 (閾值: {self.threshold_ms}ms)")

    def stop(self):
        self._stopped = True
        if self.listener is not None:
            self.listener.stop()
        self.timer.stop()
        self.key_buffer.clear()

    def _on_press(self, key):
        """pynput 的回呼函數，執行於獨立執行緒"""
        try:
            # 取得按鍵字元 (處理一般字元與數字)
            if hasattr(key, 'char') and key.char:
                char = key.char
            elif key == keyboard.Key.enter:
                self._key_pressed.emit("", True)
                return
            else:
                return

            self._key_pressed.emit(char, False)

        except Exception:
            logger.exception("監聽按鍵異常")

    @Slot(str, bool)
    def _record_key(self, char: str, enter: bool):
        if self._stopped:
            return
        if enter:
            if self.key_buffer:
                self.timer.start(0)
        else:
            self.key_buffer.append(char)
            self.timer.start(self.threshold_ms)

    def _on_input_finished(self):
        """當計時器超時，代表讀卡機已噴完資料"""
        if not self.key_buffer:
            return

        raw_uid = "".join(self.key_buffer)

        # 1. 判定是否為「高速輸入」
        # 這裡可以加入更嚴格的檢查，例如檢查總長度是否 > 4，防止誤觸
        if len(raw_uid) >= 4:
            # 移植你原本的每兩位反轉邏輯
            final_uid = self._convert_uid(raw_uid)
            logger.info(f"[Reader] 識別到全域輸入卡號: {final_uid}")
            self.card_scanned.emit(final_uid)
        else:
            logger.debug(f"[Reader] 輸入長度不足，忽略: {raw_uid}")

        # 清空緩衝區
        self.key_buffer = []

    def _convert_uid(self, uid_str: str) -> str:
        """保持舊專案的相容性邏輯"""
        _uid = []
        for i in range(len(uid_str) - 1, 0, -2):
            _uid.extend(uid_str[i - 1:i + 1])
        return "".join(_uid)
