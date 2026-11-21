import sqlite3
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Dict, Any
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "bookings.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            full_name TEXT,
            phone TEXT,
            service_id INTEGER NOT NULL,
            service_name TEXT NOT NULL,
            duration INTEGER NOT NULL,
            price INTEGER NOT NULL,
            booking_date TEXT NOT NULL,  -- YYYY-MM-DD
            start_time TEXT NOT NULL,    -- HH:MM
            end_time TEXT NOT NULL,      -- HH:MM
            status TEXT DEFAULT 'confirmed',  -- confirmed, cancelled, completed
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reminder_sent INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS blocked_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_date TEXT NOT NULL,  -- YYYY-MM-DD
            start_time TEXT,           -- HH:MM or NULL for whole day
            end_time TEXT,             -- HH:MM or NULL
            reason TEXT,
            created_by INTEGER
        )
    """)
    conn.commit()
    conn.close()

def add_booking(user_id: int, username: str, full_name: str, phone: str,
                service_id: int, service_name: str, duration: int, price: int,
                booking_date: str, start_time: str, end_time: str) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO bookings (user_id, username, full_name, phone, service_id, service_name,
                              duration, price, booking_date, start_time, end_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, username, full_name, phone, service_id, service_name, duration, price,
          booking_date, start_time, end_time))
    booking_id = c.lastrowid
    conn.commit()
    conn.close()
    return booking_id

def get_user_bookings(user_id: int, future_only: bool = True) -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    query = "SELECT * FROM bookings WHERE user_id = ? AND status = 'confirmed'"
    params = [user_id]
    if future_only:
        query += " AND booking_date >= date('now')"
    query += " ORDER BY booking_date, start_time"
    c.execute(query, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_bookings_for_date(booking_date: str) -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM bookings WHERE booking_date = ? AND status = 'confirmed'
        ORDER BY start_time
    """, (booking_date,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def cancel_booking(booking_id: int, user_id: Optional[int] = None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    if user_id:
        c.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ? AND user_id = ?",
                  (booking_id, user_id))
    else:
        c.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def get_booking_by_id(booking_id: int) -> Optional[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def is_slot_available(booking_date: str, start_time: str, end_time: str, exclude_id: Optional[int] = None) -> bool:
    """Проверяет, свободен ли слот (нет пересечений с подтверждёнными записями и блокировками)."""
    conn = get_connection()
    c = conn.cursor()
    # Пересечения с записями
    query = """
        SELECT COUNT(*) FROM bookings
        WHERE booking_date = ? AND status = 'confirmed'
          AND NOT (end_time <= ? OR start_time >= ?)
    """
    params = [booking_date, start_time, end_time]
    if exclude_id:
        query += " AND id != ?"
        params.append(exclude_id)
    c.execute(query, params)
    if c.fetchone()[0] > 0:
        conn.close()
        return False

    # Блокировки: whole day or overlapping
    c.execute("""
        SELECT COUNT(*) FROM blocked_slots
        WHERE block_date = ?
          AND (
            (start_time IS NULL AND end_time IS NULL)  -- whole day
            OR NOT (end_time <= ? OR start_time >= ?)
          )
    """, (booking_date, start_time, end_time))
    blocked = c.fetchone()[0] > 0
    conn.close()
    return not blocked

def add_block(block_date: str, start_time: Optional[str], end_time: Optional[str],
              reason: str, created_by: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO blocked_slots (block_date, start_time, end_time, reason, created_by)
        VALUES (?, ?, ?, ?, ?)
    """, (block_date, start_time, end_time, reason, created_by))
    conn.commit()
    conn.close()

def get_blocks_for_date(block_date: str) -> List[Dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM blocked_slots WHERE block_date = ?", (block_date,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def get_upcoming_for_reminders() -> List[Dict]:
    """Записи на завтра и ближайшие часы для напоминаний."""
    conn = get_connection()
    c = conn.cursor()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    c.execute("""
        SELECT * FROM bookings
        WHERE status = 'confirmed' AND booking_date >= date('now')
          AND reminder_sent = 0
        ORDER BY booking_date, start_time
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def mark_reminder_sent(booking_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE bookings SET reminder_sent = 1 WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()

# Инициализация при импорте
init_db()
