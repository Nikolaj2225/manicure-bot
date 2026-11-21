from datetime import datetime, date, time, timedelta
from typing import List, Tuple, Optional
from services import get_service
from database import is_slot_available, get_bookings_for_date, get_blocks_for_date

# График
# 0=Monday ... 6=Sunday
WORKING_HOURS = {
    0: (time(9, 0), time(20, 0)),   # Mon
    1: (time(9, 0), time(20, 0)),   # Tue
    2: (time(9, 0), time(20, 0)),   # Wed
    3: (time(9, 0), time(20, 0)),   # Thu
    4: (time(9, 0), time(20, 0)),   # Fri
    5: (time(9, 0), time(20, 0)),   # Sat
    # 6: Sunday off
}

LUNCH_START = None  # обед отменён
LUNCH_END = None
SLOT_STEP = 30  # минут (только :00 и :30)

def is_working_day(d: date) -> bool:
    return d.weekday() in WORKING_HOURS

def get_day_hours(d: date) -> Optional[Tuple[time, time]]:
    return WORKING_HOURS.get(d.weekday())

def time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute

def minutes_to_time(m: int) -> time:
    return time(m // 60, m % 60)

def overlaps_lunch(start: time, end: time) -> bool:
    if LUNCH_START is None or LUNCH_END is None:
        return False
    s = time_to_minutes(start)
    e = time_to_minutes(end)
    ls = time_to_minutes(LUNCH_START)
    le = time_to_minutes(LUNCH_END)
    return not (e <= ls or s >= le)

def generate_available_slots(booking_date: date, duration_min: int) -> List[str]:
    """Возвращает список доступных времён начала (HH:MM) для услуги длительностью duration_min."""
    if not is_working_day(booking_date):
        return []
    hours = get_day_hours(booking_date)
    if not hours:
        return []
    day_start, day_end = hours
    date_str = booking_date.isoformat()

    # Проверяем whole-day block
    blocks = get_blocks_for_date(date_str)
    if any(b["start_time"] is None for b in blocks):
        return []

    slots = []
    current_min = time_to_minutes(day_start)
    # Последние допустимые старты: до 20:00 (конец дня остаётся свободным)
    last_allowed_start = time_to_minutes(time(20, 0))

    while current_min <= last_allowed_start:
        start_t = minutes_to_time(current_min)
        end_t = minutes_to_time(current_min + duration_min)

        # Не пересекает обед
        if overlaps_lunch(start_t, end_t):
            current_min += SLOT_STEP
            continue

        start_str = start_t.strftime("%H:%M")
        end_str = end_t.strftime("%H:%M")

        if is_slot_available(date_str, start_str, end_str):
            slots.append(start_str)

        current_min += SLOT_STEP

    return slots

def get_next_working_days(count: int = 14) -> List[date]:
    days = []
    d = date.today()
    while len(days) < count:
        d += timedelta(days=1)
        if is_working_day(d):
            days.append(d)
    return days

def format_date_ru(d: date) -> str:
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    return f"{d.strftime('%d.%m.%Y')} ({weekdays[d.weekday()]})"
