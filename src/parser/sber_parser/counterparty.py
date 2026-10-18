"""Парсинг парсинг контрагента из описания."""
import re
from typing import Optional


_PERSON_PREFIX_RE = re.compile(r"^Перевод\s+(?:от|для)\s+(.+)$")
_SENTENCE_END_RE = re.compile(r"\.(?=\s|$)")
_WORD_BEFORE_DOT_RE = re.compile(r"([^\s.\-]+)$")
_NEXT_IS_NAME_RE = re.compile(r"\s*(?:[А-ЯЁA-Z]\.|[А-ЯЁA-Z][а-яёa-z])")

def _strip_trailing_period(name: str) -> str:
    """Убирает завершающую точку, если она не закрывает инициал."""
    if not name.endswith("."):
        return name
    inner = name[:-1]
    m = _WORD_BEFORE_DOT_RE.search(inner)
    if not m or len(m.group(1)) < 2:
        return name       # одиночная буква — инициал, точку оставляем
    return inner          # слово — конец предложения, точку срезаем


def extract_person_name(description: str) -> Optional[str]:
    
    if not description: return None

    m = _PERSON_PREFIX_RE.match(description)
    if not m:
        return None
    body = m.group(1)

    for end_match in _SENTENCE_END_RE.finditer(body):
        end = end_match.start()
        before, after = body[:end], body[end_match.end():]

        word_m = _WORD_BEFORE_DOT_RE.search(before)
        word = word_m.group(1) if word_m else ""

        if len(word) >= 2:
            return _strip_trailing_period(before + ".")

        # Инициал. Продолжаем, только если он ПЕРВЫЙ в последовательности
        # (перед ним начало строки или пробел) И после него идёт ещё имя.
        is_first_initial = (
            word_m is not None
            and (word_m.start() == 0 or before[word_m.start() - 1] in " \t-")
        )
        if is_first_initial and _NEXT_IS_NAME_RE.match(after):
            continue

        return _strip_trailing_period(before + ".")

    return body.strip() or None