"""Russian UI labels for filter values (DB keys stay in English)."""

DIRECTION_LABELS = {
    "offensive": "Наступательная",
    "defensive": "Оборонительная",
    "both": "Оба направления",
}

CONTENT_TYPE_LABELS = {
    "news": "Новости",
    "writeup": "Разбор",
    "advisory": "Бюллетень",
    "release": "Релиз",
    "research": "Исследование",
    "incident_report": "Отчёт об инциденте",
}

TECHNOLOGY_LABELS = {
    "web": "Веб",
    "network": "Сеть",
    "malware": "Вредоносное ПО",
    "cloud": "Облако",
    "identity": "Идентификация",
    "mobile": "Мобильные",
    "hardware": "Железо",
}


def label_direction(value: str) -> str:
    return DIRECTION_LABELS.get(value, value)


def label_content_type(value: str) -> str:
    return CONTENT_TYPE_LABELS.get(value, value)


def label_technology(value: str) -> str:
    return TECHNOLOGY_LABELS.get(value, value)
