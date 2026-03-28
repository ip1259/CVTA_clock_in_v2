import logging
import requests
import urllib3
import calendar
from datetime import datetime, date, time, timedelta
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from database.database_manager import db_manager
from database.base import Schedule, Holiday, ShiftAssignment, Employee

logger = logging.getLogger(__name__)

# 關閉 SSL 未驗證的警告訊息 (方案一)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LegacySslAdapter(HTTPAdapter):
    """
    自定義適配器：用於解決政府網站 SSL 憑證演算法過舊或不支援安全協商的問題。
    下修安全性等級至 1 並允許 Legacy Server Connect。
    """

    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context()
        # 下修安全等級以相容舊型加密演算法 (例如 SHA1)
        context.set_ciphers('DEFAULT@SECLEVEL=1')
        # 允許與不支援安全重新協商的舊型伺服器連線
        context.options |= 0x4  # ssl.OP_LEGACY_SERVER_CONNECT
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)


class ShiftManager:
    """管理排班、班表樣板與假日設定的業務邏輯"""

    @staticmethod
    def get_all_schedules():
        """獲取所有班表樣板"""
        session = db_manager.get_session()
        try:
            return session.query(Schedule).all()
        finally:
            session.close()

    @staticmethod
    def create_schedule(name: str, job_start: time, job_end: time):
        """建立新的班表樣板 (例如: 早班 08:30-17:30)"""
        session = db_manager.get_session()
        try:
            new_sch = Schedule(name=name, job_start=job_start, job_end=job_end)
            session.add(new_sch)
            session.commit()
            logger.info(f"建立班表成功: {name} ({job_start}-{job_end})")
            return new_sch.id
        except Exception as e:
            session.rollback()
            logger.error(f"建立班表失敗: {e}")
            return None
        finally:
            session.close()

    @staticmethod
    def delete_schedule(schedule_id: int):
        """刪除班表樣板"""
        session = db_manager.get_session()
        try:
            sch = session.query(Schedule).get(schedule_id)
            if sch:
                session.delete(sch)
                session.commit()
                return True
            return False
        except Exception as e:
            session.rollback()
            return False
        finally:
            session.close()

    @staticmethod
    def assign_shift(employee_id: int, schedule_id: int | None, target_date: date):
        """指派特定日期給特定員工的班表 (單日)"""
        session = db_manager.get_session()
        try:
            # 檢查該日期是否已有指派紀錄，若有則覆蓋
            assign = session.query(ShiftAssignment).filter(
                and_(ShiftAssignment.employee_id == employee_id,
                     ShiftAssignment.date == target_date)
            ).first()

            if assign:
                assign.schedule_id = schedule_id
            else:
                new_assign = ShiftAssignment(
                    employee_id=employee_id,
                    schedule_id=schedule_id,
                    date=target_date
                )
                session.add(new_assign)

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"排班指派失敗: 員工 {employee_id} 日期 {target_date}: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def bulk_assign_shifts(employee_id: int, schedule_id: int | None, start_date: date, end_date: date):
        """批次指派日期範圍內的排班"""
        current = start_date
        success = True
        while current <= end_date:
            if not ShiftManager.assign_shift(employee_id, schedule_id, current):
                success = False
            current += timedelta(days=1)
        return success

    @staticmethod
    def get_day_assignments(target_date: date):
        """獲取特定日期所有被手動指派的員工及其班表"""
        session = db_manager.get_session()
        try:
            assignments = session.query(ShiftAssignment).options(
                joinedload(ShiftAssignment.employee)
            ).filter(
                ShiftAssignment.date == target_date
            ).all()
            return [{
                "employee_id": a.employee_id,
                "employee_name": a.employee.name,
                "schedule_id": a.schedule_id
            } for a in assignments]
        finally:
            session.close()

    @staticmethod
    def get_monthly_summary(year: int, month: int):
        """獲取特定月份所有員工的排班摘要 (僅包含手動指派)"""
        session = db_manager.get_session()
        try:
            # 計算該月範圍
            _, last_day = calendar.monthrange(year, month)
            start_date = date(year, month, 1)
            end_date = date(year, month, last_day)

            # 抓取該月所有的手動指派紀錄，並預載入員工資料
            assignments = session.query(ShiftAssignment).options(
                joinedload(ShiftAssignment.employee)
            ).filter(
                and_(
                    ShiftAssignment.date >= start_date,
                    ShiftAssignment.date <= end_date
                )
            ).all()

            # 依日期群組姓名
            summary = {}
            for a in assignments:
                d_str = a.date.isoformat()
                if d_str not in summary:
                    summary[d_str] = []
                summary[d_str].append(a.employee.name)
            return summary
        finally:
            session.close()

    @staticmethod
    def get_monthly_holidays(year: int, month: int):
        """獲取特定月份的假日資料表紀錄摘要"""
        session = db_manager.get_session()
        try:
            _, last_day = calendar.monthrange(year, month)
            start_date = date(year, month, 1)
            end_date = date(year, month, last_day)
            holidays = session.query(Holiday).filter(
                and_(Holiday.date >= start_date, Holiday.date <= end_date)
            ).all()
            # 回傳格式: {"2024-05-01": {"description": "勞動節", "is_workday": False}, ...}
            return {h.date.isoformat(): {"description": h.description, "is_workday": h.is_workday} for h in holidays}
        finally:
            session.close()

    @staticmethod
    def batch_assign_employees(target_date: date, assignments: list[dict]):
        """批次更新特定日期的排班名單 (覆蓋式更新)"""
        session = db_manager.get_session()
        try:
            # 1. 先刪除該日期原有的所有手動指派 (為了實現「減少人員」的功能)
            session.query(ShiftAssignment).filter(
                ShiftAssignment.date == target_date).delete()

            # 2. 插入新的指派名單
            for item in assignments:
                new_assign = ShiftAssignment(
                    employee_id=item['employee_id'],
                    schedule_id=item['schedule_id'],
                    date=target_date
                )
                session.add(new_assign)

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"批次指派員工失敗: 日期 {target_date}: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def fetch_holiday_candidates():
        """從政府開放資料獲取候選假日清單 (不直接寫入資料庫)"""
        logger.info("獲取政府假日候選清單中...")
        page = 0
        all_candidates = []
        session = db_manager.get_session()

        try:
            while True:
                url = f"https://data.ntpc.gov.tw/api/datasets/308dcd75-6434-45bc-a95f-584da4fed251/json?page={page}&size=500"
                try:
                    # 方案一：直接忽略 SSL 驗證，解決憑證問題
                    response = requests.get(url, timeout=10, verify=False)
                    response.raise_for_status()
                    data = response.json()
                    if not data:
                        break
                except Exception as e:
                    logger.error(f"連線政府 API 失敗 (Page {page}): {e}")
                    break

                # 2. 收集本頁需要處理的資料
                page_items = []
                for item in data:
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
                        continue

                    is_workday = item.get("isholiday", "否") == "否"
                    name = (item.get("name") or "").strip()
                    category = (item.get("holidaycategory") or "").strip()
                    description = name or category

                    is_std_workday = target_date.weekday() < 5
                    # 過濾條件：非標準工作日或有特殊名稱
                    if (is_workday != is_std_workday) or name:
                        all_candidates.append({
                            "date": target_date,
                            "is_workday": is_workday,
                            "description": description
                        })
                page += 1

            # 過濾掉已經存在於資料庫中的日期，避免前端重複顯示
            if all_candidates:
                candidate_dates = [c['date'] for c in all_candidates]
                existing_dates = session.query(Holiday.date).filter(
                    Holiday.date.in_(candidate_dates)
                ).all()
                # SQLAlchemy 回傳的是 tuple 列表 [(date1,), (date2,)]，需轉為集合加速比對
                existing_set = {d[0] for d in existing_dates}
                all_candidates = [
                    c for c in all_candidates if c['date'] not in existing_set]

            return all_candidates
        except Exception as e:
            logger.error(f"獲取政府假日清單失敗: {e}")
            return []
        finally:
            session.close()

    @staticmethod
    def apply_holidays(holiday_list: list):
        """將使用者選取的假日清單寫入或更新至資料庫"""
        session = db_manager.get_session()
        try:
            # 批次獲取現有的日期，用於決定是更新還是新增
            target_dates = [h['date'] for h in holiday_list]
            existing_map = {h.date: h for h in session.query(Holiday).filter(
                Holiday.date.in_(target_dates)).all()}

            for item in holiday_list:
                d = item['date']
                if d in existing_map:
                    # 更新現有物件
                    existing_map[d].is_workday = item['is_workday']
                    existing_map[d].description = item['description']
                else:
                    # 新增
                    session.add(Holiday(
                        date=d,
                        is_workday=item['is_workday'],
                        description=item['description']
                    ))
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"儲存假日資料失敗: {e}")
            return False
        finally:
            session.close()

    @staticmethod
    def get_employee_shift(employee_id: int, target_date: date):
        """
        核心邏輯：查詢員工在特定日期「應上班」的班表內容
        回傳 Schedule 物件或 None (代表休假)
        """
        session = db_manager.get_session()
        try:
            # 1. 優先查看是否有手動排班指派
            assign = session.query(ShiftAssignment).filter(
                and_(ShiftAssignment.employee_id == employee_id,
                     ShiftAssignment.date == target_date)
            ).first()
            if assign:
                return assign.schedule

            # 2. 檢查假日設定 (Holiday 表優先於預設週末判斷)
            holiday = session.query(Holiday).filter_by(
                date=target_date).first()
            is_workday = target_date.weekday() < 5  # 預設一至五上班
            if holiday:
                is_workday = holiday.is_workday

            if not is_workday:
                return None

            # 3. 查看員工預設班表
            emp = session.query(Employee).get(employee_id)
            if emp and emp.schedule_id:
                return session.query(Schedule).get(emp.schedule_id)

            return None
        finally:
            session.close()

    @staticmethod
    def get_monthly_shifts(employee_id: int, year: int, month: int):
        """批次獲取員工特定月份的完整排班表"""
        session = db_manager.get_session()
        try:
            # 計算該月的第一天與最後一天
            _, last_day = calendar.monthrange(year, month)
            start_date = date(year, month, 1)
            end_date = date(year, month, last_day)

            # 1. 一次性抓取該範圍內的所有手動指派
            assignments = session.query(ShiftAssignment).filter(
                and_(
                    ShiftAssignment.employee_id == employee_id,
                    ShiftAssignment.date >= start_date,
                    ShiftAssignment.date <= end_date
                )
            ).all()
            # 轉為字典以加速查找: {date: ScheduleObject}
            assign_dict = {a.date: a.schedule for a in assignments}

            # 2. 一次性抓取該月份的所有假日設定
            holidays = session.query(Holiday).filter(
                and_(Holiday.date >= start_date, Holiday.date <= end_date)
            ).all()
            holiday_map = {h.date: h.is_workday for h in holidays}

            # 3. 獲取員工預設班表
            emp = session.query(Employee).get(employee_id)
            default_sch = session.query(Schedule).get(
                emp.schedule_id) if emp and emp.schedule_id else None

            results = []
            curr = start_date
            while curr <= end_date:
                sch = None
                is_manual = False
                is_leave = False

                if curr in assign_dict:
                    sch = assign_dict[curr]
                    is_manual = True
                    # 如果手動指派但沒有班表，視為「請假/排休」
                    if sch is None:
                        is_leave = True
                else:
                    # 假日判定：先查表，若無紀錄則按標準週末判定
                    curr_is_workday = holiday_map.get(curr, curr.weekday() < 5)
                    if curr_is_workday:
                        sch = default_sch

                results.append({
                    "date": curr,
                    "schedule": sch,
                    "is_manual": is_manual,
                    "is_leave": is_leave
                })
                curr += timedelta(days=1)
            return results
        except Exception as e:
            logger.error(f"獲取排班表失敗: {e}")
            return []
        finally:
            session.close()
