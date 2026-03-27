import json
import os
import threading
import logging

logger = logging.getLogger(__name__)


class OfflineManager:
    _instance = None
    _lock = threading.Lock()  # 用於建立實例的類別鎖
    _file_lock = threading.RLock()  # 用於檔案讀寫的實例鎖

    def __new__(cls, *args, **kwargs):
        """實作 Thread-safe Singleton"""
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(OfflineManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, file_path="data/offline_punches.json"):
        # 確保 __init__ 只會在第一次被呼叫時執行初始化
        if not hasattr(self, "_initialized"):
            with self._file_lock:
                self.file_path = file_path
                os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
                self._initialized = True
                logger.info(f"[Offline] 初始化緩衝管理員，路徑: {self.file_path}")

    def save_punch(self, uid: str, timestamp: str):
        """執行緒安全地存入打卡資訊"""
        with self._file_lock:
            data = self.load_all()
            data.append({
                "uid": uid,
                "timestamp": timestamp,
                "retry_count": 0
            })
            self._write_to_file(data)
            logger.info(f"[Offline] 已暫存打卡: {uid} (共 {len(data)} 筆待傳)")

    def load_all(self) -> list:
        """執行緒安全地讀取所有暫存"""
        with self._file_lock:
            if not os.path.exists(self.file_path):
                return []
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"[Offline] 讀取暫存檔失敗: {e}")
                return []

    def remove_punches(self, uploaded_list: list):
        """
        上傳成功後，從暫存中移除已成功的項目。
        傳入的 uploaded_list 應包含完整的 {uid, timestamp} 物件。
        """
        with self._file_lock:
            current_data = self.load_all()
            # 過濾掉已經成功上傳的紀錄
            new_data = [
                item for item in current_data
                if item not in uploaded_list
            ]
            self._write_to_file(new_data)
            logger.info(f"[Offline] 清理完成，剩餘 {len(new_data)} 筆紀錄")

    def _write_to_file(self, data: list):
        """內部方法：執行實際寫入 (須在鎖內呼叫)"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"[Offline] 寫入檔案失敗: {e}")
