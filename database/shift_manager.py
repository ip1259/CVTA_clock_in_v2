import logging
from datetime import date, time
from database.database_manager import db_manager
from database.base import Schedule, Holiday, ShiftAssignment
import requests
from datetime import datetime

logger = logging.getLogger(__name__)


class ShiftManager:
    @staticmethod
    def create_schedule(name: str, start: time, end: time):
        """建立班表樣板 (如: 大夜班 22:00-06:00)"""
        session = db_manager.get_session()
        try:
            sch = Schedule(name=name, job_start=start, job_end=end)
            session.add(sch)
            session.commit()
            return sch.id
        finally:
            session.close()

    @staticmethod
    def set_holiday(target_date: date, is_workday: bool, description: str):
        """設定特殊日期 (假日或補班日)"""
        session = db_manager.get_session()
        try:
            # 使用 merge 自動判斷是新增還是更新
            holiday = session.query(Holiday).filter_by(
                date=target_date).first()
            if holiday:
                holiday.is_workday = is_workday
                holiday.description = description
            else:
                holiday = Holiday(
                    date=target_date, is_workday=is_workday,
                    description=description)
                session.add(holiday)
            session.commit()
            return True
        finally:
            session.close()

    @staticmethod
    def assign_shift(emp_id: int, sch_id: int, target_date: date):
        """指派特定員工在特定日期的班表 (輪班核心)"""
        session = db_manager.get_session()
        try:
            # 檢查是否已存在指派，若存在則更新，不存在則新增
            assignment = session.query(ShiftAssignment).filter_by(
                employee_id=emp_id, date=target_date
            ).first()

            if assignment:
                assignment.schedule_id = sch_id
            else:
                assignment = ShiftAssignment(
                    employee_id=emp_id, schedule_id=sch_id, date=target_date)
                session.add(assignment)

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"排班失敗: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def bulk_assign_shifts(emp_id: int, sch_id: int,
                           start_date: date, end_date: date):
        """批次排班 (例如幫某人排一整週的晚班)"""
        from datetime import timedelta
        current = start_date
        success = True
        while current <= end_date:
            if not ShiftManager.assign_shift(emp_id, sch_id, current):
                success = False
            current += timedelta(days=1)
        return success

    @staticmethod
    def get_all_schedules():
        session = db_manager.get_session()
        try:
            return session.query(Schedule).all()
        finally:
            session.close()

    @staticmethod
    def update_holiday_from_gov():
        """從政府資料更新國定假日"""
        page = 0
        while True:
            url = f"https://data.ntpc.gov.tw/api/datasets/308dcd75-6434-45bc-a95f-584da4fed251/json?page={page}&size=500"
            try:
                # 1. 增加 Timeout 保護與狀態檢查
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                if not data:
                    break
            except Exception as e:
                logger.error(f"連線政府 API 失敗 (Page {page}): {e}")
                break

            session = db_manager.get_session()
            try:
                for item in data:
                    # 1. 防禦性日期解析：嘗試多種常見格式
                    date_str = item.get("date")
                    if not date_str:
                        continue

                    target_date = None
                    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
                        try:
                            target_date = datetime.strptime(
                                date_str, fmt).date()
                            break
                        except ValueError:
                            continue

                    if not target_date:
                        logger.warning(f"無法解析日期格式: {date_str}，跳過該項目")
                        continue

                    is_workday = item.get("isholiday", "否") == "否"

                    # 2. 決定描述：優先用名稱 (如: 端午節)，若無則用類別 (如: 補假)
                    name = item.get("name")
                    category = item.get("holidaycategory")
                    description = name if name else (
                        category if category else "")

                    # 3. 過濾冗餘：只儲存「非標準」的日期
                    # 標準工作日: 週一(0) 到 週五(4)
                    is_std_workday = target_date.weekday() < 5

                    # 如果 API 說的跟標準不一樣 (補班或平日放假)，或是該日有特殊名稱，才存入資料庫
                    is_special = (is_workday != is_std_workday) or (
                        name and name.strip())

                    if not is_special:
                        continue

                    holiday = session.query(Holiday).filter_by(
                        date=target_date).first()
                    if holiday:
                        holiday.is_workday = is_workday
                        holiday.description = description
                    else:
                        new_holiday = Holiday(
                            date=target_date,
                            is_workday=is_workday,
                            description=description
                        )
                        session.add(new_holiday)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"更新政府假日資料失敗: {e}")
                break
            finally:
                session.close()
            page += 1
