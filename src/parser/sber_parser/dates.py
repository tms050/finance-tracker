"""Парсинг значений, связанных с датами и временем"""
import re
from datetime import date, time, datetime
from typing import Optional, Union

DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")

def parse_date(s: Union[str, date, datetime, None]) -> Optional[date]:
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def parse_time(s: Union[str, time, datetime, None]) -> Optional[time]:
    if s is None:
        return None
    if isinstance(s, datetime):
        return time(s.hour, s.minute)
    if isinstance(s, time):
        return s
    if not isinstance(s, str) or not TIME_RE.match(s):
        return None
    try:
        return datetime.strptime(s.strip(), "%H:%M").time()
    except ValueError:
        return None