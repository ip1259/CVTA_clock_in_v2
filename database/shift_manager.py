import logging
import requests
import urllib3
import calendar
from datetime import datetime, date, time, timedelta
from sqlalchemy import and_
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
    def update_holiday_from_gov():
        """從政府開放資料同步假日資料 (此處預留介面供 BackgroundTask 呼叫)"""
        logger.info("假日資料同步任務執行中...")
        page = 0
        # 1. 將 Session 提升到迴圈外，複用單一連線
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
                        page_items.append({
                            "date": target_date,
                            "is_workday": is_workday,
                            "description": description
                        })

                if page_items:
                    # 3. 解決 N+1 問題：一次性查詢本頁所有涉及的日期
                    page_dates = [x['date'] for x in page_items]
                    existing_map = {h.date: h for h in session.query(
                        Holiday).filter(Holiday.date.in_(page_dates)).all()}

                    for pi in page_items:
                        d = pi['date']
                        if d in existing_map:
                            # 更新現有物件
                            existing_map[d].is_workday = pi['is_workday']
                            existing_map[d].description = pi['description']
                        else:
                            # 新增
                            session.add(Holiday(
                                date=d,
                                is_workday=pi['is_workday'],
                                description=pi['description']
                            ))
                    # 每一頁 commit 一次，兼顧效能與記憶體
                    session.commit()

                page += 1
        except Exception as e:
            session.rollback()
            logger.error(f"同步政府假日資料發生非預期錯誤: {e}")
        finally:
            session.close()
        logger.info("假日資料同步任務完成")

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
