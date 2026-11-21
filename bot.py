import asyncio
import logging
import os
from datetime import datetime, date, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

from config import BOT_TOKEN, ADMIN_IDS, DAYS_AHEAD, BLOCK_DAYS_AHEAD, REMINDER_HOURS, TIMEZONE
from services import SERVICES, get_service, get_services_by_category
from database import (
    add_booking, get_user_bookings, cancel_booking, get_booking_by_id,
    get_bookings_for_date, is_slot_available, add_block, get_blocks_for_date,
    get_upcoming_for_reminders, mark_reminder_sent
)
from schedule import (
    generate_available_slots, get_next_working_days, format_date_ru,
    is_working_day, time_to_minutes, minutes_to_time
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# ===== FSM =====
class BookingFSM(StatesGroup):
    choosing_category = State()
    choosing_service = State()
    choosing_date = State()
    choosing_time = State()
    confirming = State()
    entering_phone = State()

class AdminFSM(StatesGroup):
    menu = State()
    choosing_date = State()
    choosing_block_type = State()  # day or interval
    entering_reason = State()
    choosing_interval_start = State()
    choosing_interval_end = State()
    viewing_bookings = State()
    # Ручная запись
    manual_service = State()
    manual_date = State()
    manual_time = State()
    manual_name = State()
    manual_phone = State()
    manual_username = State()


# ===== Keyboards =====
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записаться")],
            [KeyboardButton(text="📋 Мои записи"), KeyboardButton(text="ℹ️ Услуги и цены")],
        ],
        resize_keyboard=True
    )

def categories_kb() -> InlineKeyboardMarkup:
    cats = list(get_services_by_category().keys())
    builder = InlineKeyboardBuilder()
    for cat in cats:
        builder.button(text=cat, callback_data=f"cat:{cat}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def services_kb(category: str) -> InlineKeyboardMarkup:
    services = get_services_by_category()[category]
    builder = InlineKeyboardBuilder()
    for s in services:
        price_str = f"{s['price']:,}".replace(",", " ")
        builder.button(
            text=f"{s['name']} — {s['duration']} мин / {price_str} сум",
            callback_data=f"svc:{s['id']}"
        )
    builder.button(text="⬅️ Назад", callback_data="back_cat")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def dates_kb() -> InlineKeyboardMarkup:
    days = get_next_working_days(DAYS_AHEAD)
    builder = InlineKeyboardBuilder()
    for d in days:
        builder.button(text=format_date_ru(d), callback_data=f"date:{d.isoformat()}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()

def times_kb(slots: list[str], date_str: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(text=slot, callback_data=f"time:{date_str}:{slot}")
    builder.button(text="⬅️ Назад к датам", callback_data="back_dates")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(4)
    return builder.as_markup()

def confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm_yes")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def admin_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Расписание на сегодня", callback_data="admin:today")
    builder.button(text="📊 Загрузка на месяц", callback_data="admin:month")
    builder.button(text="📆 Расписание на дату", callback_data="admin:schedule")
    builder.button(text="🟢 Свободные окна", callback_data="admin:free")
    builder.button(text="🚫 Заблокировать день", callback_data="admin:block_day")
    builder.button(text="⏰ Заблокировать интервал", callback_data="admin:block_interval")
    builder.button(text="➕ Записать клиента вручную", callback_data="admin:manual")
    builder.button(text="❌ Отменить запись", callback_data="admin:cancel_list")
    builder.button(text="⬅️ Закрыть", callback_data="admin:close")
    builder.adjust(1)
    return builder.as_markup()

def admin_dates_kb(prefix: str, days_count: int = 14) -> InlineKeyboardMarkup:
    days = get_next_working_days(days_count)
    builder = InlineKeyboardBuilder()
    for d in days:
        builder.button(text=format_date_ru(d), callback_data=f"{prefix}:{d.isoformat()}")
    builder.button(text="⬅️ Назад", callback_data="admin:menu")
    builder.adjust(2)
    return builder.as_markup()

def my_bookings_kb(bookings: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in bookings:
        builder.button(
            text=f"{b['booking_date']} {b['start_time']} — {b['service_name'][:30]}",
            callback_data=f"viewbk:{b['id']}"
        )
    builder.button(text="⬅️ Меню", callback_data="menu")
    builder.adjust(1)
    return builder.as_markup()


# ===== Handlers: Client =====
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Добро пожаловать в бот записи на маникюр и педикюр!\n\n"
        "Выберите действие:",
        reply_markup=main_menu_kb()
    )

@router.message(F.text == "📅 Записаться")
async def start_booking(message: Message, state: FSMContext):
    await state.set_state(BookingFSM.choosing_category)
    await message.answer("Выберите категорию услуги:", reply_markup=categories_kb())

@router.callback_query(F.data.startswith("cat:"))
async def choose_category(callback: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    if current and current.startswith("AdminFSM"):
        return  # пропускаем, обработает админский хендлер
    cat = callback.data.split(":", 1)[1]
    await state.update_data(category=cat)
    await state.set_state(BookingFSM.choosing_service)
    await callback.message.edit_text(f"Категория: {cat}\nВыберите услугу:", reply_markup=services_kb(cat))
    await callback.answer()

@router.callback_query(F.data == "back_cat")
async def back_to_categories(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BookingFSM.choosing_category)
    await callback.message.edit_text("Выберите категорию услуги:", reply_markup=categories_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("svc:"))
async def choose_service(callback: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    if current and current.startswith("AdminFSM"):
        return
    svc_id = int(callback.data.split(":")[1])
    service = get_service(svc_id)
    if not service:
        await callback.answer("Услуга не найдена", show_alert=True)
        return
    await state.update_data(service_id=svc_id, service=service)
    await state.set_state(BookingFSM.choosing_date)
    await callback.message.edit_text(
        f"Услуга: {service['name']}\nДлительность: {service['duration']} мин\nЦена: {service['price']:,} сум\n\n"
        "Выберите дату:",
        reply_markup=dates_kb()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("date:"))
async def choose_date(callback: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    if current and current.startswith("AdminFSM"):
        return
    date_str = callback.data.split(":")[1]
    data = await state.get_data()
    service = data["service"]
    d = date.fromisoformat(date_str)
    slots = generate_available_slots(d, service["duration"])
    if not slots:
        await callback.answer("На эту дату нет свободных слотов", show_alert=True)
        return
    await state.update_data(booking_date=date_str)
    await state.set_state(BookingFSM.choosing_time)
    await callback.message.edit_text(
        f"Дата: {format_date_ru(d)}\nУслуга: {service['name']}\n\nВыберите время:",
        reply_markup=times_kb(slots, date_str)
    )
    await callback.answer()

@router.callback_query(F.data == "back_dates")
async def back_to_dates(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BookingFSM.choosing_date)
    await callback.message.edit_text("Выберите дату:", reply_markup=dates_kb())
    await callback.answer()

@router.callback_query(F.data.startswith("time:"))
async def choose_time(callback: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    if current and current.startswith("AdminFSM"):
        return
    # callback.data = "time:YYYY-MM-DD:HH:MM"
    parts = callback.data.split(":")
    date_str = parts[1]
    start_str = f"{parts[2]}:{parts[3]}"
    data = await state.get_data()
    service = data["service"]
    duration = service["duration"]
    start_min = time_to_minutes(datetime.strptime(start_str, "%H:%M").time())
    end_min = start_min + duration
    end_str = minutes_to_time(end_min).strftime("%H:%M")

    # Финальная проверка доступности
    if not is_slot_available(date_str, start_str, end_str):
        await callback.answer("Это время уже занято. Выберите другое.", show_alert=True)
        return

    await state.update_data(start_time=start_str, end_time=end_str)
    await state.set_state(BookingFSM.entering_phone)
    # Нельзя edit_text с ReplyKeyboardMarkup — отправляем новое сообщение
    await callback.message.answer(
        "Отправьте ваш номер телефона для связи\n"
        "(или нажмите кнопку ниже):",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Отправить контакт", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True
        )
    )
    await callback.answer()

@router.message(BookingFSM.entering_phone, F.contact)
async def got_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    await state.update_data(phone=phone, full_name=message.from_user.full_name)
    await show_confirmation(message, state)

@router.message(BookingFSM.entering_phone, F.text)
async def got_phone_text(message: Message, state: FSMContext):
    phone = message.text.strip()
    await state.update_data(phone=phone, full_name=message.from_user.full_name)
    await show_confirmation(message, state)

async def show_confirmation(message: Message, state: FSMContext):
    data = await state.get_data()
    service = data["service"]
    text = (
        "📋 Подтвердите запись:\n\n"
        f"Услуга: {service['name']}\n"
        f"Дата: {data['booking_date']}\n"
        f"Время: {data['start_time']} — {data['end_time']}\n"
        f"Цена: {service['price']:,} сум\n"
        f"Телефон: {data.get('phone', '—')}\n"
        f"Имя: {data.get('full_name', message.from_user.full_name)}"
    )
    await state.set_state(BookingFSM.confirming)
    await message.answer(text, reply_markup=confirm_kb())
    await message.answer("Или вернитесь в меню:", reply_markup=main_menu_kb())

@router.callback_query(F.data == "confirm_yes", BookingFSM.confirming)
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    service = data["service"]
    user = callback.from_user
    booking_id = add_booking(
        user_id=user.id,
        username=user.username,
        full_name=data.get("full_name", user.full_name),
        phone=data.get("phone", ""),
        service_id=service["id"],
        service_name=service["name"],
        duration=service["duration"],
        price=service["price"],
        booking_date=data["booking_date"],
        start_time=data["start_time"],
        end_time=data["end_time"]
    )
    await state.clear()
    await callback.message.edit_text(
        f"✅ Запись #{booking_id} подтверждена!\n\n"
        f"{service['name']}\n"
        f"{data['booking_date']} в {data['start_time']}\n\n"
        "Мы напомним вам о визите. До встречи! 💅"
    )
    await callback.message.answer("Меню:", reply_markup=main_menu_kb())
    # Уведомить админов
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🆕 Новая запись #{booking_id}\n"
                f"{user.full_name} (@{user.username or '—'})\n"
                f"{service['name']}\n"
                f"{data['booking_date']} {data['start_time']}-{data['end_time']}\n"
                f"Тел: {data.get('phone', '—')}"
            )
        except Exception:
            pass
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def cancel_flow(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Запись отменена.")
    await callback.message.answer("Меню:", reply_markup=main_menu_kb())
    await callback.answer()

@router.message(F.text == "📋 Мои записи")
async def my_bookings(message: Message):
    bookings = get_user_bookings(message.from_user.id)
    if not bookings:
        await message.answer("У вас нет активных записей.", reply_markup=main_menu_kb())
        return
    await message.answer("Ваши записи:", reply_markup=my_bookings_kb(bookings))

@router.callback_query(F.data.startswith("viewbk:"))
async def view_booking(callback: CallbackQuery):
    bid = int(callback.data.split(":")[1])
    b = get_booking_by_id(bid)
    if not b or b["user_id"] != callback.from_user.id:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    text = (
        f"Запись #{b['id']}\n"
        f"{b['service_name']}\n"
        f"{b['booking_date']} {b['start_time']}–{b['end_time']}\n"
        f"Цена: {b['price']:,} сум\n"
        f"Статус: {b['status']}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"cancelbk:{bid}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_bookings")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("cancelbk:"))
async def cancel_my_booking(callback: CallbackQuery):
    bid = int(callback.data.split(":")[1])
    success = cancel_booking(bid, callback.from_user.id)
    if success:
        await callback.message.edit_text("✅ Запись отменена.")
    else:
        await callback.answer("Не удалось отменить", show_alert=True)
    await callback.answer()

@router.callback_query(F.data == "my_bookings")
async def back_my_bookings(callback: CallbackQuery):
    bookings = get_user_bookings(callback.from_user.id)
    if not bookings:
        await callback.message.edit_text("У вас нет активных записей.")
        return
    await callback.message.edit_text("Ваши записи:", reply_markup=my_bookings_kb(bookings))
    await callback.answer()

@router.message(F.text == "ℹ️ Услуги и цены")
async def show_services(message: Message):
    text = "💅 Прайс-лист:\n\n"
    for cat, svcs in get_services_by_category().items():
        text += f"**{cat}**\n"
        for s in svcs:
            text += f"• {s['name']} — {s['duration']} мин / {s['price']:,} сум\n"
        text += "\n"
    await message.answer(text, parse_mode="Markdown")

# ===== Admin =====
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def show_admin_menu(message_or_callback, state: FSMContext = None):
    text = "🔧 Админ-меню\n\nВыберите действие:"
    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=admin_main_kb())
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, reply_markup=admin_main_kb())
    if state:
        await state.set_state(AdminFSM.menu)

@router.message(Command("admin"))
async def admin_menu_cmd(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await show_admin_menu(message, state)

@router.callback_query(F.data == "admin:menu")
async def admin_menu_cb(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await show_admin_menu(callback, state)

@router.callback_query(F.data == "admin:close")
async def admin_close(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Админ-меню закрыто.")
    await callback.answer()

@router.callback_query(F.data == "admin:today")
async def admin_today_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    today = date.today().isoformat()
    bookings = get_bookings_for_date(today)
    blocks = get_blocks_for_date(today)
    text = f"📅 Сегодня ({today})\n\n"
    if blocks:
        text += "🚫 Блокировки:\n" + "\n".join(
            f"• {b['start_time'] or 'Весь день'}–{b['end_time'] or ''} ({b['reason']})" for b in blocks
        ) + "\n\n"
    if bookings:
        text += "📋 Записи:\n"
        for b in bookings:
            text += f"#{b['id']} {b['start_time']}-{b['end_time']} {b['service_name']}\n  {b['full_name']} {b['phone']}\n"
    else:
        text += "Записей нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin:month")
async def admin_month_overview(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    today = date.today()
    # Берём текущий и два следующих месяца
    months = []
    y, m = today.year, today.month
    for _ in range(3):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    text = "📊 Загрузка на ближайшие 3 месяца\n\n"
    builder = InlineKeyboardBuilder()

    for year, month in months:
        # Дни месяца
        import calendar
        cal = calendar.monthcalendar(year, month)
        month_name = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                      "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"][month]
        text += f"**{month_name} {year}**\n"

        for week in cal:
            week_days = []
            for day in week:
                if day == 0:
                    continue
                d = date(year, month, day)
                if d < today:
                    continue
                if not is_working_day(d):
                    continue
                bookings = get_bookings_for_date(d.isoformat())
                count = len(bookings)
                # Простая индикация загрузки
                if count == 0:
                    mark = "🟢"
                elif count <= 3:
                    mark = "🟡"
                else:
                    mark = "🔴"
                week_days.append(f"{d.day:02d}{mark}")
            if week_days:
                text += "  " + "  ".join(week_days) + "\n"
        text += "\n"
        builder.button(text=f"📅 {month_name}", callback_data=f"admin_month:{year}-{month:02d}")

    builder.button(text="⬅️ Назад", callback_data="admin:menu")
    builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data.startswith("admin_month:"))
async def admin_month_detail(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    ym = callback.data.split(":")[1]  # YYYY-MM
    year, month = map(int, ym.split("-"))
    import calendar
    cal = calendar.monthcalendar(year, month)
    month_name = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"][month]

    text = f"📊 {month_name} {year} — выберите день\n\n"
    builder = InlineKeyboardBuilder()
    today = date.today()

    for week in cal:
        for day in week:
            if day == 0:
                continue
            d = date(year, month, day)
            if d < today or not is_working_day(d):
                continue
            bookings = get_bookings_for_date(d.isoformat())
            count = len(bookings)
            mark = "🟢" if count == 0 else ("🟡" if count <= 3 else "🔴")
            builder.button(
                text=f"{d.day:02d} {mark} ({count})",
                callback_data=f"admin_day:{d.isoformat()}"
            )
    builder.button(text="⬅️ К месяцам", callback_data="admin:month")
    builder.button(text="⬅️ Меню", callback_data="admin:menu")
    builder.adjust(3)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("admin_day:"))
async def admin_day_detail(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    date_str = callback.data.split(":")[1]
    d = date.fromisoformat(date_str)
    bookings = get_bookings_for_date(date_str)
    blocks = get_blocks_for_date(date_str)

    text = f"📅 {format_date_ru(d)}\n\n"
    if blocks:
        text += "🚫 Блокировки:\n" + "\n".join(
            f"• {b['start_time'] or 'Весь день'}–{b['end_time'] or ''} ({b['reason']})" for b in blocks
        ) + "\n\n"
    if bookings:
        text += "📋 Записи:\n"
        for b in bookings:
            text += (
                f"#{b['id']} {b['start_time']}-{b['end_time']}\n"
                f"  {b['service_name']}\n"
                f"  {b['full_name']} {b['phone']}\n\n"
            )
    else:
        text += "Записей нет."

    ym = f"{d.year}-{d.month:02d}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К месяцу", callback_data=f"admin_month:{ym}")],
        [InlineKeyboardButton(text="⬅️ Меню", callback_data="admin:menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin:schedule")
async def admin_choose_date_schedule(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.update_data(admin_action="schedule")
    await callback.message.edit_text("Выберите дату:", reply_markup=admin_dates_kb("admin_date"))
    await callback.answer()

@router.callback_query(F.data == "admin:free")
async def admin_choose_date_free(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.update_data(admin_action="free")
    await callback.message.edit_text("Выберите дату для просмотра свободных окон:", reply_markup=admin_dates_kb("admin_date"))
    await callback.answer()

@router.callback_query(F.data == "admin:block_day")
async def admin_block_day_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.update_data(admin_action="block_day")
    await callback.message.edit_text("Выберите день для полной блокировки:", reply_markup=admin_dates_kb("admin_date", BLOCK_DAYS_AHEAD))
    await callback.answer()

@router.callback_query(F.data == "admin:block_interval")
async def admin_block_interval_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.update_data(admin_action="block_interval")
    await callback.message.edit_text("Выберите день для блокировки интервала:", reply_markup=admin_dates_kb("admin_date", BLOCK_DAYS_AHEAD))
    await callback.answer()

@router.callback_query(F.data.startswith("admin_date:"))
async def admin_date_selected(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    date_str = callback.data.split(":")[1]
    data = await state.get_data()
    action = data.get("admin_action")
    await state.update_data(selected_date=date_str)
    d = date.fromisoformat(date_str)

    if action == "schedule":
        bookings = get_bookings_for_date(date_str)
        blocks = get_blocks_for_date(date_str)
        text = f"📅 {format_date_ru(d)}\n\n"
        if blocks:
            text += "🚫 Блокировки:\n" + "\n".join(
                f"• {b['start_time'] or 'Весь день'}–{b['end_time'] or ''} ({b['reason']})" for b in blocks
            ) + "\n\n"
        if bookings:
            text += "📋 Записи:\n"
            for b in bookings:
                text += f"#{b['id']} {b['start_time']}-{b['end_time']} {b['service_name']}\n  {b['full_name']} {b['phone']}\n"
        else:
            text += "Записей нет."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]])
        await callback.message.edit_text(text, reply_markup=kb)

    elif action == "free":
        # Показываем свободные окна (примерно по 30-60 мин шагам, как примерные окна)
        slots_60 = generate_available_slots(d, 60)
        slots_30 = generate_available_slots(d, 30)
        text = f"🟢 Свободные окна на {format_date_ru(d)}\n\n"
        text += f"Для услуг ~30 мин: {', '.join(slots_30[:12]) or 'нет'}\n"
        text += f"Для услуг ~60 мин: {', '.join(slots_60[:10]) or 'нет'}\n\n"
        text += "(Полный список слотов зависит от выбранной услуги клиентом)"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]])
        await callback.message.edit_text(text, reply_markup=kb)

    elif action == "block_day":
        await state.set_state(AdminFSM.entering_reason)
        await state.update_data(block_type="day")
        await callback.message.edit_text(
            f"Блокировка всего дня {format_date_ru(d)}\n\nНапишите причину (болезнь, отпуск и т.п.):"
        )

    elif action == "block_interval":
        await state.set_state(AdminFSM.entering_reason)
        await state.update_data(block_type="interval")
        await callback.message.edit_text(
            f"Блокировка интервала на {format_date_ru(d)}\n\nНапишите причину, затем укажите время:"
        )

    await callback.answer()

@router.message(AdminFSM.entering_reason)
async def admin_reason_entered(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    reason = message.text.strip()
    data = await state.get_data()
    await state.update_data(reason=reason)
    block_type = data.get("block_type")
    date_str = data.get("selected_date")

    if block_type == "day":
        add_block(date_str, None, None, reason, message.from_user.id)
        await message.answer(f"✅ День {date_str} полностью заблокирован.\nПричина: {reason}")
        await state.clear()
        await show_admin_menu(message)
    else:
        # Interval: ask for start-end
        await state.set_state(AdminFSM.choosing_interval_start)
        await message.answer(
            "Укажите интервал в формате HH:MM-HH:MM\nПример: 13:00-15:30\nили 09:15-11:00"
        )

@router.message(AdminFSM.choosing_interval_start)
async def admin_interval_entered(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = message.text.strip()
    if "-" not in text:
        await message.answer("Неверный формат. Пример: 13:00-15:30")
        return
    try:
        start, end = [t.strip() for t in text.split("-")]
        # Простая валидация
        datetime.strptime(start, "%H:%M")
        datetime.strptime(end, "%H:%M")
    except Exception:
        await message.answer("Неверный формат времени. Пример: 13:00-15:30")
        return

    data = await state.get_data()
    date_str = data["selected_date"]
    reason = data["reason"]
    add_block(date_str, start, end, reason, message.from_user.id)
    await message.answer(f"✅ Интервал {start}–{end} на {date_str} заблокирован.\nПричина: {reason}")
    await state.clear()
    await show_admin_menu(message)

# ===== Ручная запись клиента админом =====
@router.callback_query(F.data == "admin:manual")
async def admin_manual_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminFSM.manual_service)
    # Отдельные callback’и, чтобы не конфликтовать с клиентским потоком
    builder = InlineKeyboardBuilder()
    for cat in get_services_by_category().keys():
        builder.button(text=cat, callback_data=f"adm_cat:{cat}")
    builder.button(text="❌ Отмена", callback_data="admin:menu")
    builder.adjust(1)
    await callback.message.edit_text(
        "Ручная запись клиента.\nВыберите категорию услуги:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(AdminFSM.manual_service, F.data.startswith("adm_cat:"))
async def admin_manual_category(callback: CallbackQuery, state: FSMContext):
    cat = callback.data.split(":", 1)[1]
    await state.update_data(category=cat)
    builder = InlineKeyboardBuilder()
    for s in get_services_by_category()[cat]:
        price_str = f"{s['price']:,}".replace(",", " ")
        builder.button(
            text=f"{s['name']} — {s['duration']} мин / {price_str} сум",
            callback_data=f"adm_svc:{s['id']}"
        )
    builder.button(text="⬅️ Назад", callback_data="admin:manual")
    builder.button(text="❌ Отмена", callback_data="admin:menu")
    builder.adjust(1)
    await callback.message.edit_text(f"Категория: {cat}\nВыберите услугу:", reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(AdminFSM.manual_service, F.data.startswith("adm_svc:"))
async def admin_manual_service(callback: CallbackQuery, state: FSMContext):
    svc_id = int(callback.data.split(":")[1])
    service = get_service(svc_id)
    if not service:
        await callback.answer("Услуга не найдена", show_alert=True)
        return
    await state.update_data(service_id=svc_id, service=service)
    await state.set_state(AdminFSM.manual_date)
    # Уникальные callback’и для дат
    days = get_next_working_days(DAYS_AHEAD)
    builder = InlineKeyboardBuilder()
    for d in days:
        builder.button(text=format_date_ru(d), callback_data=f"adm_date:{d.isoformat()}")
    builder.button(text="❌ Отмена", callback_data="admin:menu")
    builder.adjust(2)
    await callback.message.edit_text(
        f"Услуга: {service['name']}\nВыберите дату:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(AdminFSM.manual_date, F.data.startswith("adm_date:"))
async def admin_manual_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":")[1]
    data = await state.get_data()
    service = data["service"]
    d = date.fromisoformat(date_str)
    slots = generate_available_slots(d, service["duration"])
    if not slots:
        await callback.answer("На эту дату нет свободных слотов", show_alert=True)
        return
    await state.update_data(booking_date=date_str)
    await state.set_state(AdminFSM.manual_time)
    # Уникальные callback’и для времени
    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(text=slot, callback_data=f"adm_time:{date_str}:{slot}")
    builder.button(text="⬅️ Назад", callback_data="admin:manual")
    builder.button(text="❌ Отмена", callback_data="admin:menu")
    builder.adjust(4)
    await callback.message.edit_text(
        f"Дата: {format_date_ru(d)}\nВыберите время:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(AdminFSM.manual_time, F.data.startswith("adm_time:"))
async def admin_manual_time(callback: CallbackQuery, state: FSMContext):
    # adm_time:YYYY-MM-DD:HH:MM
    parts = callback.data.split(":")
    date_str = parts[1]
    start_str = f"{parts[2]}:{parts[3]}"
    data = await state.get_data()
    service = data["service"]
    duration = service["duration"]
    start_min = time_to_minutes(datetime.strptime(start_str, "%H:%M").time())
    end_min = start_min + duration
    end_str = minutes_to_time(end_min).strftime("%H:%M")

    if not is_slot_available(date_str, start_str, end_str):
        await callback.answer("Это время уже занято.", show_alert=True)
        return

    await state.update_data(start_time=start_str, end_time=end_str)
    await state.set_state(AdminFSM.manual_name)
    await callback.message.edit_text("Введите имя клиента:")
    await callback.answer()

@router.message(AdminFSM.manual_name)
async def admin_manual_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(client_name=message.text.strip())
    await state.set_state(AdminFSM.manual_phone)
    await message.answer("Введите номер телефона клиента:")

@router.message(AdminFSM.manual_phone)
async def admin_manual_phone(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    phone = message.text.strip()
    await state.update_data(phone=phone)
    await state.set_state(AdminFSM.manual_username)
    await message.answer(
        "Введите Telegram-username клиента (например @ivan)\n"
        "или отправьте «-», если его нет / не знаете.\n\n"
        "Если клиент хотя бы раз писал боту — напоминания будут приходить."
    )

@router.message(AdminFSM.manual_username)
async def admin_manual_username(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = message.text.strip()
    username = None
    user_id = 0

    if raw != "-" and raw:
        username = raw.lstrip("@")
        # Пытаемся найти user_id по прошлым записям
        from database import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT user_id FROM bookings WHERE username = ? AND user_id > 0 ORDER BY id DESC LIMIT 1",
            (username,)
        )
        row = c.fetchone()
        conn.close()
        if row:
            user_id = row[0]

    data = await state.get_data()
    service = data["service"]

    booking_id = add_booking(
        user_id=user_id,
        username=username,
        full_name=data["client_name"],
        phone=data["phone"],
        service_id=service["id"],
        service_name=service["name"],
        duration=service["duration"],
        price=service["price"],
        booking_date=data["booking_date"],
        start_time=data["start_time"],
        end_time=data["end_time"]
    )
    await state.clear()

    reminder_note = ""
    if user_id:
        reminder_note = "\n✅ Напоминания будут приходить клиенту."
    elif username:
        reminder_note = "\n⚠️ Username сохранён, но клиент ещё не писал боту — напоминания пока не уйдут."
    else:
        reminder_note = "\nℹ️ Username не указан."

    # Готовое сообщение для пересылки клиенту
    bot_link = "https://t.me/Nasibuwanailbot"
    forward_text = (
        f"Здравствуйте, {data['client_name']}!\n\n"
        f"Вы записаны:\n"
        f"{service['name']}\n"
        f"{data['booking_date']} в {data['start_time']}\n\n"
        f"Чтобы получить напоминание о визите, нажмите Start в боте:\n"
        f"{bot_link}"
    )

    await message.answer(
        f"✅ Клиент записан вручную!\n\n"
        f"#{booking_id}\n"
        f"{service['name']}\n"
        f"{data['booking_date']} {data['start_time']}–{data['end_time']}\n"
        f"{data['client_name']}\n"
        f"Тел: {data['phone']}\n"
        f"Username: @{username or '—'}"
        f"{reminder_note}\n\n"
        f"📋 Сообщение для клиента (можно скопировать и отправить):\n\n"
        f"{forward_text}"
    )
    await show_admin_menu(message)

@router.callback_query(F.data == "admin:cancel_list")
async def admin_cancel_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    # Показываем все записи в пределах периода записи клиентов
    from datetime import timedelta
    end_date = (date.today() + timedelta(days=DAYS_AHEAD)).isoformat()
    from database import get_connection
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM bookings 
        WHERE status = 'confirmed' 
          AND booking_date >= date('now') 
          AND booking_date <= ?
        ORDER BY booking_date, start_time
    """, (end_date,))
    bookings = [dict(r) for r in c.fetchall()]
    conn.close()
    if not bookings:
        await callback.message.edit_text("Нет активных записей для отмены.",
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:menu")]]))
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    for b in bookings:
        # Более подробная подпись кнопки
        name = (b.get("full_name") or "—")[:15]
        service_short = b["service_name"][:18]
        phone = (b.get("phone") or "")[-4:]  # последние 4 цифры
        phone_str = f" …{phone}" if phone else ""
        btn_text = f"#{b['id']} {b['booking_date'][5:]} {b['start_time']} {name}{phone_str} | {service_short}"
        # Обрезаем до безопасной длины
        if len(btn_text) > 60:
            btn_text = btn_text[:57] + "…"
        builder.button(
            text=btn_text,
            callback_data=f"admin_cancel:{b['id']}"
        )
    builder.button(text="⬅️ Назад", callback_data="admin:menu")
    builder.adjust(1)
    await callback.message.edit_text(
        "Выберите запись для отмены:\n"
        "(формат: #номер дата время имя …тел | услуга)",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("admin_cancel:"))
async def admin_do_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    bid = int(callback.data.split(":")[1])
    b = get_booking_by_id(bid)
    if not b:
        await callback.answer("Не найдена", show_alert=True)
        return
    cancel_booking(bid)
    try:
        await bot.send_message(
            b["user_id"],
            f"⚠️ Ваша запись #{bid} на {b['booking_date']} {b['start_time']} была отменена администратором."
        )
    except Exception:
        pass
    await callback.message.edit_text(f"✅ Запись #{bid} отменена.")
    await callback.answer()

# Оставляем старые команды для совместимости
@router.message(Command("today"))
async def admin_today(message: Message):
    if not is_admin(message.from_user.id):
        return
    today = date.today().isoformat()
    bookings = get_bookings_for_date(today)
    if not bookings:
        await message.answer("На сегодня записей нет.")
        return
    text = f"📅 Записи на {today}:\n\n"
    for b in bookings:
        text += f"#{b['id']} {b['start_time']}-{b['end_time']} {b['service_name']}\n  {b['full_name']} {b['phone']}\n"
    await message.answer(text)

# ===== Reminders =====
async def reminder_loop():
    while True:
        try:
            upcoming = get_upcoming_for_reminders()
            now = datetime.now()
            for b in upcoming:
                booking_dt = datetime.fromisoformat(f"{b['booking_date']} {b['start_time']}")
                hours_left = (booking_dt - now).total_seconds() / 3600
                for rh in REMINDER_HOURS:
                    if rh - 0.5 <= hours_left <= rh + 0.5 and not b["reminder_sent"]:
                        try:
                            await bot.send_message(
                                b["user_id"],
                                f"⏰ Напоминание о записи!\n\n"
                                f"{b['service_name']}\n"
                                f"{b['booking_date']} в {b['start_time']}\n\n"
                                "Ждём вас! Если нужно перенести — отмените и запишитесь заново."
                            )
                            mark_reminder_sent(b["id"])
                        except Exception as e:
                            logger.warning(f"Не удалось отправить напоминание {b['id']}: {e}")
        except Exception as e:
            logger.error(f"Ошибка в reminder_loop: {e}")
        await asyncio.sleep(1800)  # каждые 30 минут

# ===== Startup =====
async def health(request):
    return web.Response(text="ok")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server started on port {port}")

async def main():
    dp.include_router(router)
    asyncio.create_task(reminder_loop())
    asyncio.create_task(start_web())
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
