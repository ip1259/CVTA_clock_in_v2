from datetime import datetime
from sqlalchemy import (Column, Integer, String, DateTime,
                        ForeignKey, Boolean, Time, Index,
                        Date)
from sqlalchemy.orm import relationship, declarative_base


Base = declarative_base()


class Schedule(Base):
    """新增：班表定義，解決 config.json 靈活性不足的問題"""
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)  # 如 "一般日班"
    job_start = Column(Time, nullable=False)  # 對應舊版 config["job_start"]
    job_end = Column(Time, nullable=False)   # 對應舊版 config["job_end"]


class Employee(Base):
    """對應舊版 employees 表"""
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    nickname = Column(String(50))
    is_active = Column(Boolean, default=True)  # 新增：離職標記
    schedule_id = Column(Integer, ForeignKey("schedules.id"))  # 預設班表
    schedule = relationship("Schedule")

    # 關聯設定
    cards = relationship("Card", back_populates="owner",
                         cascade="all, delete-orphan")
    records = relationship("Record", back_populates="employee")
    assignments = relationship("ShiftAssignment", back_populates="employee")


class Card(Base):
    """對應舊版 cards 表"""
    __tablename__ = "cards"
    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(50), unique=True, nullable=False)
    # 兼容建議：舊版是用 user_name 關聯，新版改用 employee_id
    employee_id = Column(Integer, ForeignKey(
        "employees.id", ondelete="CASCADE"))

    owner = relationship("Employee", back_populates="cards")


class Record(Base):
    """打卡紀錄表：冷熱庫結構完全相同"""
    __tablename__ = "records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(50), nullable=False)
    employee_id = Column(Integer, ForeignKey(
        "employees.id", ondelete="CASCADE"))

    # 關鍵優化：為時間加上索引，加速「冷熱邊界」的搜尋與搬運
    record_time = Column(DateTime, default=datetime.now,
                         nullable=False, index=True)
    note = Column(String(255))  # 新增：儲存備註或手動打卡事由

    employee = relationship("Employee", back_populates="records")

    # 複合索引：加速查詢「特定員工在特定時間段」的紀錄
    __table_args__ = (
        Index('ix_employee_time', 'employee_id', 'record_time'),
    )


class Account(Base):
    """對應舊版 accounts 表"""
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)  # 儲存加密後的密碼


class Holiday(Base):
    """新增：國定假日、彈性放假與補班日定義"""
    __tablename__ = "holidays"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, unique=True, nullable=False, index=True)
    # is_workday 為 False: 代表這天是放假日（即使是平日）
    # is_workday 為 True:  代表這天是補班日（即使是週末）
    is_workday = Column(Boolean, default=False, nullable=False)
    description = Column(String(100))  # 例如 "春節", "中秋節補班"


class ShiftAssignment(Base):
    """新增：每日排班指派（解決輪班、換班需求）"""
    __tablename__ = "shift_assignments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    schedule_id = Column(Integer, ForeignKey("schedules.id", ondelete="CASCADE"), nullable=True)
    date = Column(Date, nullable=False, index=True)
    schedule = relationship("Schedule")
    employee = relationship("Employee", back_populates="assignments")

    # 複合索引：確保同一個員工在同一天不會有兩個班表
    __table_args__ = (Index('ix_emp_date_shift', 'employee_id', 'date', unique=True),)
