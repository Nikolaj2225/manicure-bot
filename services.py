# Услуги маникюр/педикюр бота
# duration в минутах, price в сумах
# Обновлено по актуальному прайсу

SERVICES = [
    # Маникюр
    {"id": 1, "name": "Маникюр без покрытия", "duration": 60, "price": 200000, "category": "Маникюр"},
    {"id": 2, "name": "Японский маникюр", "duration": 60, "price": 250000, "category": "Маникюр"},
    {"id": 3, "name": "Маникюр гель покрытием (короткие ногти)", "duration": 90, "price": 300000, "category": "Маникюр"},
    {"id": 4, "name": "Маникюр гель покрытием (длинные ногти)", "duration": 120, "price": 350000, "category": "Маникюр"},
    # Дополнительно
    {"id": 5, "name": "Френч", "duration": 15, "price": 50000, "category": "Дополнительно"},
    {"id": 6, "name": "Дизайн ногтей", "duration": 20, "price": 50000, "category": "Дополнительно"},
    {"id": 7, "name": "Снятие", "duration": 15, "price": 50000, "category": "Дополнительно"},
    # Педикюр
    {"id": 8, "name": "Педикюр без покрытия", "duration": 60, "price": 250000, "category": "Педикюр"},
    {"id": 9, "name": "Педикюр сложный", "duration": 90, "price": 300000, "category": "Педикюр"},
    {"id": 10, "name": "Педикюр с покрытием", "duration": 90, "price": 350000, "category": "Педикюр"},
    {"id": 19, "name": "Педикюр с покрытием сложный", "duration": 120, "price": 350000, "category": "Педикюр"},
    {"id": 11, "name": "Смарт педикюр", "duration": 60, "price": 350000, "category": "Педикюр"},
    {"id": 12, "name": "Вросшие ногти", "duration": 20, "price": 100000, "category": "Педикюр"},
    {"id": 13, "name": "Установка титановой нити (1 палец)", "duration": 40, "price": 300000, "category": "Педикюр"},
    # Мужские
    {"id": 14, "name": "Мужской маникюр", "duration": 60, "price": 250000, "category": "Мужской"},
    {"id": 15, "name": "Мужской педикюр", "duration": 60, "price": 350000, "category": "Мужской"},
    # Комплексы
    {"id": 16, "name": "Маникюр гель + педикюр обычный", "duration": 150, "price": 550000, "category": "Комплекс"},
    {"id": 17, "name": "Маникюр гель + педикюр с покрытием", "duration": 180, "price": 600000, "category": "Комплекс"},
    {"id": 18, "name": "Маникюр + педикюр обычный", "duration": 120, "price": 450000, "category": "Комплекс"},
    {"id": 20, "name": "Мужской маникюр + педикюр", "duration": 120, "price": 500000, "category": "Комплекс"},
]

def get_service(service_id: int):
    return next((s for s in SERVICES if s["id"] == service_id), None)

def get_services_by_category():
    cats = {}
    for s in SERVICES:
        cats.setdefault(s["category"], []).append(s)
    return cats
