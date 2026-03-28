import os
import jwt
from contextlib import asynccontextmanager
from datetime import datetime, date, time, timedelta, timezone
from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from database.database_manager import db_manager
import logging
from log_config import setup_logging

from database.hr_manager import HRManager
from database.shift_manager import ShiftManager
from database.record_manager import RecordManager
from web.export import _create_attendance_workbook, export_attendance

# ── Pydantic Schemas ──────────────────────────────────────────

# 初始化日誌
setup_logging()
logger = logging.getLogger(__name__)


class PunchRequest(BaseModel):
    uid: str
    timestamp: str  # 格式: YYYY-MM-DD HH:MM:SS


class EmployeeCreate(BaseModel):
    name: str
    nickname: Optional[str] = None
    schedule_id: Optional[int] = None
    card_uids: Optional[List[str]] = None


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    nickname: Optional[str] = None
    schedule_id: Optional[int] = None


class CardBindRequest(BaseModel):
    employee_id: int
    uid: str


class ScheduleCreate(BaseModel):
    name: str
    job_start: str  # HH:MM
    job_end: str    # HH:MM


class ShiftAssignRequest(BaseModel):
    employee_id: int
    schedule_id: Optional[int] = None
    target_date: date


class BatchAssignmentItem(BaseModel):
    employee_id: int
    schedule_id: Optional[int] = None


class BatchShiftRequest(BaseModel):
    assignments: List[BatchAssignmentItem]
    target_date: date


class BulkShiftAssignRequest(BaseModel):
    employee_id: int
    schedule_id: Optional[int] = None
    start_date: date
    end_date: date


class LoginRequest(BaseModel):
    username: str
    password: str


class AccountCreateRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    username: str
    old_password: str
    new_password: str


class CardCreateRequest(BaseModel):
    uid: str


class SystemMigrateRequest(BaseModel):
    old_db_path: str


class HolidayItem(BaseModel):
    date: date
    is_workday: bool
    description: str


class HolidayApplyRequest(BaseModel):
    holidays: List[HolidayItem]

# ── JWT Security Setup ────────────────────────────────────────


SECRET_KEY = "CVTA_ADMIN_SECRET_KEY_CHANGE_ME"  # 實務上應從環境變數讀取
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12  # Token 有效期 12 小時

security = HTTPBearer()


def create_access_token(data: dict):
    """建立 JWT Token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + \
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def verify_token(
        auth: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """驗證 Token 的依賴項"""
    try:
        payload = jwt.decode(auth.credentials, SECRET_KEY,
                             algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

# ── App Setup ────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """伺服器啟動時，自動初始化資料庫結構與預設帳號"""
    db_manager.init_db()
    yield


app = FastAPI(title="CVTA Clock-in System API", lifespan=lifespan)

# 支援開發環境下的 Vue 跨域請求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API v1 Routes ───────────────────────────────────────────

# 1. 考勤打卡 (供 reader_client.py 呼叫)


@app.post("/api/v1/punch")
async def punch_card(req: PunchRequest):
    try:
        dt = datetime.strptime(req.timestamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format")

    res = RecordManager.add_record_by_uid(req.uid, dt)
    if res is None:
        # 雖然卡號不認識，但我們仍回傳 200 或特定錯誤供 Client 處理離線邏輯
        raise HTTPException(status_code=404, detail="Card UID not recognized")

    rec_id, emp_name = res
    return {"status": "ok", "record_id": rec_id, "employee_name": emp_name}


@app.get("/api/v1/records")
async def get_records(
    employee_id: int,
    start_date: date,
    end_date: date,
    _=Depends(verify_token)
):
    """查詢指定員工在時間範圍內的原始打卡紀錄"""
    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.max)
    records = RecordManager.get_employee_records(employee_id, start_dt, end_dt)
    return [
        {
            "id": r.id,
            "uid": r.uid,
            "record_time": r.record_time.strftime("%Y-%m-%d %H:%M:%S")
        } for r in records
    ]

# 2. 人事管理


@app.get("/api/v1/employees")
async def get_employees(active_only: bool = True, _=Depends(verify_token)):
    emps = HRManager.get_all_employees(only_active=active_only)
    return [{
        "id": e.id,
        "name": e.name,
        "nickname": e.nickname,
        "is_active": e.is_active,
        "schedule_id": e.schedule_id
    } for e in emps]


@app.post("/api/v1/employees")
async def add_employee(req: EmployeeCreate, _=Depends(verify_token)):
    emp_id = HRManager.add_employee(
        req.name, req.nickname, req.schedule_id, req.card_uids)
    return {"id": emp_id}


@app.put("/api/v1/employees/{emp_id}")
async def update_employee(emp_id: int, req: EmployeeUpdate, _=Depends(verify_token)):
    success = HRManager.update_employee(emp_id, **req.dict(exclude_unset=True))
    if not success:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"status": "updated"}


@app.post("/api/v1/employees/bind-card")
async def bind_card(req: CardBindRequest, _=Depends(verify_token)):
    success = HRManager.bind_card(req.employee_id, req.uid)
    if not success:
        raise HTTPException(status_code=400, detail="Binding failed")
    return {"status": "ok"}


@app.put("/api/v1/employees/{emp_id}/status")
async def update_employee_status(emp_id: int, is_active: bool, _=Depends(verify_token)):
    success = HRManager.set_employee_active_status(emp_id, is_active)
    if not success:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"status": "updated"}

# 3. 排班與班表管理


@app.get("/api/v1/schedules")
async def get_schedules(_=Depends(verify_token)):
    schs = ShiftManager.get_all_schedules()
    return [{"id": s.id, "name": s.name, "start": s.job_start.strftime("%H:%M"), "end": s.job_end.strftime("%H:%M")} for s in schs]


@app.post("/api/v1/schedules")
async def create_schedule(req: ScheduleCreate, _=Depends(verify_token)):
    try:
        s_time = datetime.strptime(req.job_start, "%H:%M").time()
        e_time = datetime.strptime(req.job_end, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Time must be HH:MM")

    sid = ShiftManager.create_schedule(req.name, s_time, e_time)
    return {"id": sid}


@app.delete("/api/v1/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, _=Depends(verify_token)):
    """刪除班表樣板"""
    if ShiftManager.delete_schedule(schedule_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Schedule template not found")


@app.post("/api/v1/shifts/assign")
async def assign_shift(req: ShiftAssignRequest, _=Depends(verify_token)):
    success = ShiftManager.assign_shift(
        req.employee_id, req.schedule_id, req.target_date)
    if not success:
        raise HTTPException(status_code=500, detail="Assignment failed")
    return {"status": "ok"}


@app.get("/api/v1/shifts/day-summary")
async def get_day_summary(target_date: date, _=Depends(verify_token)):
    """獲取特定日期的所有排班人員清單"""
    return ShiftManager.get_day_assignments(target_date)


@app.get("/api/v1/shifts/monthly-summary")
async def get_overall_monthly_summary(year: int, month: int, _=Depends(verify_token)):
    """獲取單月所有員工的排班摘要，供總體排班日曆使用"""
    return ShiftManager.get_monthly_summary(year, month)


@app.get("/api/v1/holidays/monthly")
async def get_monthly_holidays(year: int, month: int, _=Depends(verify_token)):
    """獲取單月的所有假日設定，供總體排班日曆顯示"""
    return ShiftManager.get_monthly_holidays(year, month)


@app.post("/api/v1/shifts/batch-assign")
async def batch_assign_shifts(req: BatchShiftRequest, _=Depends(verify_token)):
    success = ShiftManager.batch_assign_employees(
        req.target_date, [item.dict() for item in req.assignments])
    if not success:
        raise HTTPException(status_code=500, detail="Batch assignment failed")
    return {"status": "ok"}


@app.post("/api/v1/shifts/bulk-assign")
async def bulk_assign_shifts(req: BulkShiftAssignRequest, _=Depends(verify_token)):
    success = ShiftManager.bulk_assign_shifts(
        req.employee_id, req.schedule_id, req.start_date, req.end_date)
    return {"status": "ok" if success else "partial_failure"}


@app.get("/api/v1/shifts/query")
async def query_employee_shift(employee_id: int, target_date: date, _=Depends(verify_token)):
    """
    查詢員工在特定日期應上的班表內容 (考慮了個人排班、預設班表與週末)
    """
    sch = ShiftManager.get_employee_shift(employee_id, target_date)
    if not sch:
        return {"employee_id": employee_id, "date": target_date, "schedule": None, "is_holiday": True}

    return {
        "employee_id": employee_id,
        "date": target_date,
        "schedule": {"id": sch.id, "name": sch.name, "start": sch.job_start.strftime("%H:%M"), "end": sch.job_end.strftime("%H:%M")},
        "is_holiday": False
    }


@app.get("/api/v1/shifts/calendar")
async def get_monthly_calendar(employee_id: int, year: int, month: int, _=Depends(verify_token)):
    """獲取員工單月完整的排班表，供前端日曆組件使用"""
    days = ShiftManager.get_monthly_shifts(employee_id, year, month)
    return [
        {
            "date": d["date"].isoformat(),
            "is_manual": d["is_manual"],
            "is_leave": d["is_leave"],
            "is_holiday": d["schedule"] is None,
            "schedule": {
                "id": d["schedule"].id,
                "name": d["schedule"].name,
                "start": d["schedule"].job_start.strftime("%H:%M"),
                "end": d["schedule"].job_end.strftime("%H:%M")
            } if d["schedule"] else None
        } for d in days
    ]

# 4. 假日管理 (政府資料同步)


@app.get("/api/v1/holidays/candidates", response_model=List[HolidayItem])
async def get_holiday_candidates(_=Depends(verify_token)):
    """獲取政府假日候選清單供前端選擇"""
    return ShiftManager.fetch_holiday_candidates()


@app.post("/api/v1/holidays/apply")
async def apply_holidays(req: HolidayApplyRequest, _=Depends(verify_token)):
    """儲存使用者勾選的假日資料"""
    success = ShiftManager.apply_holidays([h.model_dump() for h in req.holidays])
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save holidays")
    return {"status": "ok"}

# 5. 報表匯出


@app.get("/api/v1/export/attendance")
async def download_attendance(
    year: int,
    month: int,
    employee_ids: List[int] = Query(...),
    _=Depends(verify_token)
):
    """
    匯出 Excel 報表
    範例: /api/v1/export/attendance?year=2024&month=5&employee_ids=1&employee_ids=2
    """
    logger.debug(f"e_ids: {employee_ids}")
    wb = _create_attendance_workbook(employee_ids, year, month)
    stream = export_attendance(wb, year, month, export_type="bytes")

    filename = f"Attendance_{year}_{month}.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# 6. 帳號管理 (管理員權限)

@app.post("/api/v1/login")
async def login(req: LoginRequest):
    """管理員登入驗證"""
    if HRManager.verify_admin_login(req.username, req.password):
        token = create_access_token(data={"sub": req.username})
        return {
            "status": "ok",
            "access_token": token,
            "token_type": "bearer"
        }
    raise HTTPException(status_code=401, detail="Invalid username or password")


@app.post("/api/v1/accounts")
async def create_account(req: AccountCreateRequest, _=Depends(verify_token)):
    """建立新的管理員帳號"""
    success = HRManager.create_admin_account(req.username, req.password)
    if not success:
        raise HTTPException(status_code=400, detail="Account creation failed")
    return {"status": "ok"}


@app.delete("/api/v1/accounts/{username}")
async def delete_account(username: str, _=Depends(verify_token)):
    """刪除管理員帳號"""
    success = HRManager.delete_admin_account(username)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok"}


@app.put("/api/v1/accounts/password")
async def change_admin_password(req: PasswordChangeRequest, _=Depends(verify_token)):
    success, message = HRManager.change_admin_password(
        req.username, req.old_password, req.new_password
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "ok", "message": message}


# 7. 卡片管理 (管理員權限)

@app.get("/api/v1/cards")
async def get_all_cards(_=Depends(verify_token)):
    """獲取系統中所有卡片"""
    cards = HRManager.get_all_cards()
    return [
        {
            "id": c.id,
            "uid": c.uid,
            "employee_id": c.employee_id,
            "owner_name": c.owner.name if c.owner else None
        } for c in cards
    ]


@app.delete("/api/v1/cards/{card_id}")
async def delete_card(card_id: int, _=Depends(verify_token)):
    """刪除指定的卡片紀錄"""
    if HRManager.delete_card(card_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Card not found")


@app.put("/api/v1/cards/{card_id}/unbind")
async def unbind_card(card_id: int, _=Depends(verify_token)):
    """解除卡片與員工的綁定"""
    if HRManager.unbind_card(card_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Card not found")


@app.get("/api/v1/cards/unassigned")
async def get_unassigned_cards(_=Depends(verify_token)):
    """獲取尚未分配員工的卡片列表"""
    cards = HRManager.get_unassigned_cards()
    return [{"id": c.id, "uid": c.uid} for c in cards]


@app.post("/api/v1/cards/empty")
async def add_empty_card(req: CardCreateRequest, _=Depends(verify_token)):
    """新增一張無人使用的空卡"""
    success, message = HRManager.add_empty_card(req.uid)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "ok", "message": message}

# ── 系統維護 ──────────────────────────────────────────────────


@app.post("/api/v1/system/migrate")
async def migrate_database(req: SystemMigrateRequest, _=Depends(verify_token)):
    """從舊版資料庫遷移資料"""
    if not os.path.exists(req.old_db_path):
        raise HTTPException(status_code=404, detail="找不到指定的舊資料庫檔案路徑")

    try:
        db_manager.migrate_from_old_db(req.old_db_path)
        return {"status": "ok", "message": "資料遷移完成"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"遷移過程發生錯誤: {str(e)}")

# ── 前端 SPA 支援 ─────────────────────────────────────────────

# 假設 Vue build 完的檔案放在 'dist' 資料夾
FRONTEND_DIR = os.path.join(os.getcwd(), "dist")

if os.path.exists(FRONTEND_DIR):
    # 掛載靜態資源 (js, css, img)
    app.mount(
        "/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_vue_app(full_path: str):
        """
        處理所有非 API 的路徑，全部導向 Vue 的 index.html。
        這解決了 Vue Router (History mode) 重新整理頁面會 404 的問題。
        """
        # 如果路徑看起來像檔案 (有副檔名)，嘗試回傳該檔案
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)

        # 否則一律回傳 index.html 讓前端路由接手
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
else:
    @app.get("/")
    async def root_warning():
        return {"message": "Frontend build directory 'dist' not found. Please build Vue app first."}

# ── 啟動伺服器 ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    # 從環境變數讀取伺服器設定，若無則使用預設值
    host = os.getenv("CVTA_API_HOST", "0.0.0.0")
    port = int(os.getenv("CVTA_API_PORT", 16688))
    # 啟動時建議使用 --proxy-headers 如果放在 Nginx 後面
    uvicorn.run(app, host=host, port=port)
