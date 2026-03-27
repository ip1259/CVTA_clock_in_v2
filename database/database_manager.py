import os
import sqlite3
import logging
import hashlib
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from database.base import Base, Employee, Card, Record, Schedule, Account

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path: str = "data/punch_hot.db"):
        # 1. 確保資料夾存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.hot_db_path = db_path
        self.hot_db_url = f"sqlite:///{db_path}"
        self.archive_dir = "./data/archives"

        # 2. 增加 connect_args 以處理 SQLite 併發鎖定 (5秒等待)
        self.hot_engine = create_engine(
            self.hot_db_url, connect_args={"timeout": 5})
        self.HotSession = sessionmaker(bind=self.hot_engine)
        self._archive_engines = {}  # 用於快取冷庫引擎

        if not os.path.exists(self.archive_dir):
            os.makedirs(self.archive_dir)

    def init_db(self):
        """初始化資料庫表結構"""
        Base.metadata.create_all(self.hot_engine)
        logger.info("資料庫結構初始化完成")

        # 檢查並新增預設帳號 (如果目前沒有任何帳號)
        session = self.HotSession()
        try:
            if session.query(Account).count() == 0:
                default_user = "admin"
                default_pass = "admin"
                pwd_hash = hashlib.sha256(default_pass.encode()).hexdigest()
                
                new_acc = Account(username=default_user, password_hash=pwd_hash)
                session.add(new_acc)
                session.commit()
                logger.info(f"系統初次建立，已新增預設帳號: {default_user}/{default_pass}")
        except Exception as e:
            session.rollback()
            logger.error(f"建立預設帳號時發生錯誤: {e}")
        finally:
            session.close()

    def get_session(self, year: int = None):
        """
        根據年份動態取得 Session
        :param year: 如果傳入年份，則連接該年的冷庫；不傳則連接熱庫
        """
        if year is None or year == datetime.now().year:
            return self.HotSession()

        # 3. 快取引擎避免重複建立
        if year not in self._archive_engines:
            archive_url = f"sqlite:///{self.archive_dir}/punch_{year}.db"
            # 冷庫通常只讀，這裡設定長一點的 timeout
            engine = create_engine(archive_url, connect_args={"timeout": 10})

            # 確保冷庫的 Table 結構也存在 (初次連線時執行)
            Base.metadata.create_all(engine)
            self._archive_engines[year] = sessionmaker(bind=engine)

        return self._archive_engines[year]()

    # ── 遷移邏輯 (從 migrate.py 整合) ──────────────────────────────────

    def migrate_from_old_db(self, old_db_path: str):
        """從舊版 sqlite 遷移資料"""
        self.init_db()
        session = self.HotSession()
        old_conn = sqlite3.connect(old_db_path)
        old_cursor = old_conn.cursor()

        try:
            # A. 初始化預設班表 (加入重複檢查)
            default_schedule = session.query(Schedule).filter_by(name="早班").first()
            if not default_schedule:
                default_schedule = Schedule(
                    name="早班",
                    job_start=datetime.strptime("08:30", "%H:%M").time(),
                    job_end=datetime.strptime("17:30", "%H:%M").time()
                )
                session.add(default_schedule)
            session.flush()

            # B. 遷移 Employees
            old_cursor.execute("SELECT id, name, nickname FROM employees")
            name_to_id = {}
            for row in old_cursor.fetchall():
                new_emp = Employee(
                    name=row[1], nickname=row[2], schedule_id=default_schedule.id)
                session.add(new_emp)
                session.flush()
                name_to_id[row[1]] = new_emp.id

            # C. 遷移 Cards 並建立 UID 到 Employee ID 的快速查找
            uid_to_emp_id = {}
            old_cursor.execute("SELECT uid, user_name FROM cards")
            for row in old_cursor.fetchall():
                uid, user_name = row
                if user_name in name_to_id:
                    emp_id = name_to_id[user_name]
                    new_card = Card(uid=uid, employee_id=emp_id)
                    session.add(new_card)
                    uid_to_emp_id[uid] = emp_id

            # D. 遷移 Records (修正了原先變數未定義的問題)
            logger.info("正在遷移打卡紀錄，這可能需要一點時間...")
            old_cursor.execute("SELECT uid, record_time FROM records")
            
            record_batch = []
            batch_size = 1000
            
            for row in old_cursor.fetchall():
                uid, r_time = row
                if uid in uid_to_emp_id:
                    # 健壯的日期解析
                    dt_obj = None
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                        try:
                            dt_obj = datetime.strptime(r_time, fmt)
                            break
                        except ValueError:
                            continue
                    
                    if not dt_obj:
                        try: dt_obj = datetime.fromisoformat(r_time)
                        except: continue

                    new_record = Record(
                        uid=uid, employee_id=uid_to_emp_id[uid], record_time=dt_obj)
                    record_batch.append(new_record)
                
                if len(record_batch) >= batch_size:
                    session.bulk_save_objects(record_batch)
                    record_batch = []

            if record_batch:
                session.bulk_save_objects(record_batch)

            session.commit()
            logger.info("✅ 遷移完成！")
        except Exception as e:
            session.rollback()
            logger.error(f"❌ 遷移失敗: {e}")
            raise
        finally:
            old_conn.close()
            session.close()

    # ── 維護與存檔邏輯 (從 maintenance.py 整合) ──────────────────────────

    def archive_previous_year_data(self):
        """將去年的紀錄移至冷庫，並清理熱庫"""
        now = datetime.now()
        target_year = now.year - 1
        cold_db_path = os.path.join(
            self.archive_dir, f"punch_{target_year}.db")

        year_start = f"{target_year}-01-01 00:00:00"
        year_end = f"{target_year}-12-31 23:59:59"
        delete_boundary = f"{target_year}-12-01 00:00:00"
        date_start = f"{target_year}-01-01"
        date_end = f"{target_year}-12-31"
        date_del_boundary = f"{target_year}-12-01"

        # 使用原生連線執行跨庫操作 (SQLite ATTACH 語法最有效率)
        conn = self.hot_engine.raw_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(f"ATTACH DATABASE '{cold_db_path}' AS cold_db")
            # 確保冷庫結構
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cold_db.records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid VARCHAR(50) NOT NULL,
                    employee_id INTEGER,
                    record_time DATETIME NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cold_db.holidays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL UNIQUE,
                    is_workday BOOLEAN NOT NULL,
                    description VARCHAR(100)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cold_db.shift_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL,
                    schedule_id INTEGER,
                    date DATE NOT NULL,
                    UNIQUE(employee_id, date)
                )
            """)

            # 同步資料
            logger.info(f"[維護] 開始同步 {target_year} 紀錄至冷庫...")

            # A. 同步 Holidays
            cursor.execute(f"""
                INSERT INTO cold_db.holidays (date, is_workday, description)
                SELECT date, is_workday, description FROM main.holidays
                WHERE date >= '{date_start}' AND date <= '{date_end}'
                AND NOT EXISTS (SELECT 1 FROM cold_db.holidays c WHERE c.date = main.holidays.date)
            """)

            # B. 同步 ShiftAssignments
            cursor.execute(f"""
                INSERT INTO cold_db.shift_assignments (employee_id, schedule_id, date)
                SELECT employee_id, schedule_id, date FROM main.shift_assignments
                WHERE date >= '{date_start}' AND date <= '{date_end}'
                AND NOT EXISTS (
                    SELECT 1 FROM cold_db.shift_assignments c
                    WHERE c.employee_id = main.shift_assignments.employee_id
                    AND c.date = main.shift_assignments.date
                )
            """)

            # C. 同步 Records
            cursor.execute(f"""
                INSERT INTO cold_db.records (uid, employee_id, record_time)
                SELECT uid, employee_id, record_time FROM main.records
                WHERE record_time >= '{year_start}' AND record_time <= '{year_end}'
                AND NOT EXISTS (
                    SELECT 1 FROM cold_db.records c
                    WHERE c.uid = main.records.uid AND c.record_time = main.records.record_time
                )
            """)

            # 清理熱庫 (保留 12 月)
            cursor.execute(
                f"DELETE FROM main.holidays WHERE date >= '{date_start}' AND date < '{date_del_boundary}'")
            cursor.execute(
                f"DELETE FROM main.shift_assignments WHERE date >= '{date_start}' AND date < '{date_del_boundary}'")

            cursor.execute(
                f"DELETE FROM main.records WHERE record_time >= '{year_start}' AND record_time < '{delete_boundary}'")

            conn.commit()
            cursor.execute("VACUUM")
            logger.info(f"[維護] {target_year} 年度歸檔完成")
        except Exception as e:
            conn.rollback()
            logger.error(f"歸檔失敗: {e}")
            raise
        finally:
            try:
                cursor.execute("DETACH DATABASE cold_db")
            except:
                pass
            conn.close()


db_manager = DatabaseManager()
