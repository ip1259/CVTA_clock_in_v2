import logging
from database.database_manager import db_manager
from database.base import Employee, Card

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
            new_card = Card(uid=uid, employee_id=emp_id)
            session.add(new_card)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            return False
        finally:
            session.close()
