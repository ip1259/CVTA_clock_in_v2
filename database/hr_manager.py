import logging
import hashlib
from sqlalchemy.orm import joinedload
from database.database_manager import db_manager
from database.base import Employee, Card, Account

logger = logging.getLogger(__name__)


class HRManager:
    @staticmethod
    def add_employee(name: str, nickname: str = None, schedule_id: int = None, card_uids: list[str] = None):
        """新增員工並綁定卡號"""
        session = db_manager.get_session()
        try:
            new_emp = Employee(name=name, nickname=nickname,
                               schedule_id=schedule_id)
            session.add(new_emp)
            session.flush()  # 取得 new_emp.id

            if card_uids:
                for uid in card_uids:
                    # 檢查卡片是否已存在 (例如透過 reader_client 先新增的空卡)
                    card = session.query(Card).filter_by(uid=uid).first()
                    if card:
                        # 更新現有卡片的員工 ID
                        card.employee_id = new_emp.id
                    else:
                        # 新增全新卡片紀錄
                        new_card = Card(uid=uid, employee_id=new_emp.id)
                        session.add(new_card)

            session.commit()
            logger.info(f"員工 {name} 新增成功 (ID: {new_emp.id})")
            return new_emp.id
        except Exception as e:
            session.rollback()
            logger.error(f"新增員工失敗: {e}")
            raise
        finally:
            session.close()

    @staticmethod
    def update_employee(emp_id: int, **kwargs):
        """更新員工資訊 (例如修改姓名、預設班表)"""
        session = db_manager.get_session()
        try:
            emp = session.query(Employee).get(emp_id)
            if not emp:
                return False

            for key, value in kwargs.items():
                if hasattr(emp, key):
                    setattr(emp, key, value)

            session.commit()
            return True
        finally:
            session.close()

    @staticmethod
    def set_employee_active_status(emp_id: int, is_active: bool):
        """處理員工離職/復職"""
        return HRManager.update_employee(emp_id, is_active=is_active)

    @staticmethod
    def get_all_employees(only_active: bool = True):
        """獲取員工清單"""
        session = db_manager.get_session()
        try:
            query = session.query(Employee)
            if only_active:
                query = query.filter(Employee.is_active == True)
            return query.all()
        finally:
            session.close()

    @staticmethod
    def bind_card(emp_id: int, uid: str):
        """為現有員工增綁新卡"""
        session = db_manager.get_session()
        try:
            # 檢查卡片是否已存在
            card = session.query(Card).filter_by(uid=uid).first()
            if card:
                # 如果卡片已存在，直接更新擁有者 (將其從空卡轉為正式卡)
                card.employee_id = emp_id
            else:
                # 如果是系統從未見過的卡片，才新增紀錄
                new_card = Card(uid=uid, employee_id=emp_id)
                session.add(new_card)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            return False
        finally:
            session.close()

    @staticmethod
    def change_admin_password(username: str, old_password: str, new_password: str):
        """修改管理員密碼，需驗證舊密碼"""
        session = db_manager.get_session()
        try:
            acc = session.query(Account).filter_by(username=username).first()
            if not acc:
                return False, "帳號不存在"

            # 驗證舊密碼
            if acc.password_hash != HRManager._hash_password(old_password):
                return False, "舊密碼錯誤"

            # 設定新密碼
            acc.password_hash = HRManager._hash_password(new_password)
            session.commit()
            logger.info(f"管理員 {username} 密碼修改成功")
            return True, "修改成功"
        except Exception as e:
            session.rollback()
            logger.error(f"修改密碼失敗: {e}")
            return False, str(e)
        finally:
            session.close()

    # ── 管理員帳號管理 (人事權限相關) ──────────────────────────────

    @staticmethod
    def _hash_password(password: str) -> str:
        """內部方法：密碼加密邏輯 (SHA256)"""
        # 在實際生產環境建議使用 werkzeug.security 或 passlib
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def create_admin_account(username: str, password: str):
        """建立管理員帳號"""
        session = db_manager.get_session()
        try:
            if session.query(Account).filter_by(username=username).first():
                logger.warning(f"帳號建立失敗: {username} 已存在")
                return False

            new_acc = Account(
                username=username,
                password_hash=HRManager._hash_password(password)
            )
            session.add(new_acc)
            session.commit()
            logger.info(f"管理員帳號 {username} 建立成功")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"建立帳號失敗: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def verify_admin_login(username: str, password: str) -> bool:
        """驗證管理員登入"""
        session = db_manager.get_session()
        try:
            acc = session.query(Account).filter_by(username=username).first()
            if acc and acc.password_hash == HRManager._hash_password(password):
                logger.info(f"管理員 {username} 登入成功")
                return True
            return False
        finally:
            session.close()

    @staticmethod
    def delete_admin_account(username: str):
        """刪除管理員帳號"""
        session = db_manager.get_session()
        try:
            acc = session.query(Account).filter_by(username=username).first()
            if acc:
                session.delete(acc)
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            return False
        finally:
            session.close()

    @staticmethod
    def add_empty_card(uid: str):
        """新增一張尚未分配員工的空卡"""
        session = db_manager.get_session()
        try:
            # 檢查卡號是否已存在
            if session.query(Card).filter_by(uid=uid).first():
                return False, "卡號已存在"

            new_card = Card(uid=uid, employee_id=None)
            session.add(new_card)
            session.commit()
            logger.info(f"成功新增未分配空卡: {uid}")
            return True, "成功新增空卡"
        except Exception as e:
            session.rollback()
            logger.error(f"新增空卡失敗: {e}")
            return False, str(e)
        finally:
            session.close()

    @staticmethod
    def get_unassigned_cards():
        """取得所有尚未分配員工的卡片列表"""
        session = db_manager.get_session()
        try:
            return session.query(Card).filter(Card.employee_id == None).all()
        finally:
            session.close()

    @staticmethod
    def get_all_cards():
        """獲取所有卡片清單 (含擁有者資訊)"""
        session = db_manager.get_session()
        try:
                # 使用 joinedload 確保在 Session 關閉前一併抓取關聯的 owner 資料
                return session.query(Card).options(joinedload(Card.owner)).all()
        finally:
            session.close()

    @staticmethod
    def delete_card(card_id: int):
        """刪除卡片紀錄"""
        session = db_manager.get_session()
        try:
            card = session.query(Card).get(card_id)
            if card:
                session.delete(card)
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"刪除卡片失敗: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def unbind_card(card_id: int):
        """解除卡片與員工的綁定 (轉為空卡)"""
        session = db_manager.get_session()
        try:
            card = session.query(Card).get(card_id)
            if card:
                card.employee_id = None
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            logger.error(f"解除綁定失敗: {e}")
            return False
        finally:
            session.close()
