import logging
from PySide6.QtCore import QObject, Signal, QTimer
from pynput import keyboard

logger = logging.getLogger(__name__)


class GlobalCardReader(QObject):
    # 當識別出一串完整的卡號時發送
    card_scanned = Signal(str)

    def __init__(self, threshold_ms: int = 50):
        super().__init__()
        self.threshold_ms = threshold_ms
        self.key_buffer = []

        # 使用 PySide6 的 QTimer 處理超時判定
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._on_input_finished)

        # 全域鍵盤監聽器 (pynput)
        self.listener = keyboard.Listener(on_press=self._on_press)

    def start(self):
        self.listener.start()
        logger.info(f"[Reader] 全域監聽已啟動 (閾值: {self.threshold_ms}ms)")

    def stop(self):
        self.listener.stop()
        self.timer.stop()

    def _on_press(self, key):
        """pynput 的回呼函數，執行於獨立執行緒"""
        try:
            # 取得按鍵字元 (處理一般字元與數字)
            if hasattr(key, 'char') and key.char:
                char = key.char
            elif key == keyboard.Key.enter:
                # 有些讀卡機會送 Enter，直接觸發完成
                self._on_input_finished()
                return
            else:
                return

            # 每按下一顆鍵，就重新計時
            self.key_buffer.append(char)

            # 使用 QTimer.singleShot 或是透過信號回到主執行緒重置 Timer
            # 這裡為了簡潔，直接在主執行緒範圍內重置
            self.timer.start(self.threshold_ms)

        except Exception as e:
            logger.error(f"監聽按鍵異常: {e}")

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
