import logging
from datetime import datetime
from sqlalchemy import and_
from database.database_manager import db_manager
from database.base import Record, Employee, Card

logger = logging.getLogger(__name__)


class RecordManager:
    """管理實際打卡紀錄的業務邏輯"""

    @staticmethod
    def get_employee_records(employee_id: int, start_time: datetime, end_time: datetime):
        """
        獲取特定員工在特定時間範圍內的打卡紀錄
        """
        session = db_manager.get_session()
        try:
            records = session.query(Record).filter(
                and_(
                    Record.employee_id == employee_id,
                    Record.record_time >= start_time,
                    Record.record_time <= end_time
                )
            ).order_by(Record.record_time.asc()).all()
            return records
        finally:
            session.close()

    @staticmethod
    def add_record_by_uid(uid: str, record_time: datetime):
        """
        透過 UID 與時間直接新增打卡紀錄 (自動查找員工)
        """
        session = db_manager.get_session()
        try:
            # 1. 透過 UID 查找對應的卡片以取得員工 ID
            card = session.query(Card).filter(Card.uid == uid).first()
            if not card:
                logger.warning(f"打卡失敗: 找不到 UID 為 {uid} 的卡片設定")
                return None

            # 2. 建立打卡紀錄
            new_record = Record(
                uid=uid,
                employee_id=card.employee_id,
                record_time=record_time
            )
            session.add(new_record)
            session.commit()
            logger.info(f"UID 打卡成功: {uid} (員工 ID: {card.employee_id}), 時間: {record_time}")
            return new_record.id
        except Exception as e:
            session.rollback()
            logger.error(f"UID 打卡寫入失敗: {e}")
            return None
        finally:
            session.close()

    @staticmethod
    def add_manual_record(employee_id: int, record_time: datetime, uid: str = None):
        """
        手動補錄打卡紀錄（例如員工忘記帶卡）
        """
        session = db_manager.get_session()
        try:
            # 如果沒有提供 UID，嘗試抓取該員工的第一張卡片 UID
            if not uid:
                emp = session.query(Employee).get(employee_id)
                if emp and emp.cards:
                    uid = emp.cards[0].uid
                else:
                    uid = "MANUAL_ENTRY"  # 備案：標記為手動輸入

            new_record = Record(
                employee_id=employee_id,
                record_time=record_time,
                uid=uid
            )
            session.add(new_record)
            session.commit()
            logger.info(f"手動補打卡成功: 員工ID {employee_id}, 時間 {record_time}")
            return new_record.id
        except Exception as e:
            session.rollback()
            logger.error(f"手動補打卡失敗: {e}")
            return None
        finally:
            session.close()

    @staticmethod
    def update_record_time(record_id: int, new_time: datetime):
        """
        修正打卡紀錄的時間
        """
        session = db_manager.get_session()
        try:
            record = session.query(Record).get(record_id)
            if record:
                old_time = record.record_time
                record.record_time = new_time
                session.commit()
                logger.info(f"修正打卡紀錄 {record_id}: {old_time} -> {new_time}")
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"修正打卡紀錄失敗: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def delete_record(record_id: int):
        """
        刪除錯誤的打卡紀錄
        """
        session = db_manager.get_session()
        try:
            record = session.query(Record).get(record_id)
            if record:
                session.delete(record)
                session.commit()
                logger.info(f"已刪除打卡紀錄: {record_id}")
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"刪除紀錄失敗: {e}")
            return False
        finally:
            session.close()
