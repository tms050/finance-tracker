"""Конфигурация парсера выписки Сбера."""
import re
from dataclasses import dataclass
from typing import NamedTuple

_NAME_TAIL = r"[а-яёa-zА-ЯЁA-Z»\"']{2,}"

@dataclass(slots=True)
class ParserConfig:
    # Определение границ колонок
    time_boundary_ratio: float = 0.53
    header_anchor_words: tuple[str, ...] = ("ДАТА", "КАТЕГОРИЯ", "СУММА", "ОСТАТОК")

    # Регулярные выражения
    auth_re: re.Pattern[str] = re.compile(r"^\d{6}$")

    transfer_bank_re: re.Pattern[str] = re.compile(
        r"^(Перевод\s+в\s+.+?" + _NAME_TAIL + r")\."
    )
    transfer_person_re: re.Pattern[str] = re.compile(
        r"^Перевод\s+(?:от|для)\s+(.+?" + _NAME_TAIL + r")\."
    )
    first_sentence_re: re.Pattern[str] = re.compile(r"^(.+?)\.(?:\s|$)")

    # Маркеры конца таблицы / футера
    footer_phrases: tuple[str, ...] = (
        "дата формирования документа",
        "документ подписан",
        "сведения о сертификате",
        "продолжение на следующей странице",
    )

    # Маркер конца шапки таблицы
    header_marker: str = "код авторизации"

    # Иные параметры
    line_tolerance: int = 3
    header_search_limit: float = 0.8
    shape_window: int = 100

    def __post_init__(self) -> None:
        if not 0.0 < self.time_boundary_ratio < 1.0:
            raise ValueError(
                f"time_boundary_ratio должен быть в (0, 1), "
                f"получено {self.time_boundary_ratio!r}"
            )
        if not 0.0 < self.header_search_limit <= 1.0:
            raise ValueError(
                f"header_search_limit должен быть в (0, 1], "
                f"получено {self.header_search_limit!r}"
            )
        if self.line_tolerance <= 0:
            raise ValueError(
                f"line_tolerance должен быть > 0, получено {self.line_tolerance!r}"
            )
        if self.shape_window <= 0:
            raise ValueError(
                f"shape_window должен быть > 0, получено {self.shape_window!r}"
            )
        if not any(w.strip() for w in self.header_anchor_words):
            raise ValueError("header_anchor_words не может быть пустым")
        if not any(p.strip() for p in self.footer_phrases):
            raise ValueError("footer_phrases не может быть пустым")
        if not self.header_marker.strip():
            raise ValueError("header_marker не может быть пустым или состоять из пробелов")


class Interval(NamedTuple):
    """Полуинтервал [x0, x1) по горизонтальной оси в PDF-координатах."""
    x0: float
    x1: float

_COLUMNS = ("date", "time", "category", "amount", "balance")

@dataclass(slots=True)
class ColumnLayout:
    date:     Interval
    time:     Interval
    category: Interval
    amount:   Interval
    balance:  Interval

    def __post_init__(self) -> None:
        # Приводим входные кортежи к Interval (совместимость с tuple-вызовами).
        for name in _COLUMNS:
            v = getattr(self, name)
            iv = v if isinstance(v, Interval) else Interval(*v)
            setattr(self, name, Interval(float(iv.x0), float(iv.x1)))

        # Проверяем, что каждый интервал непустой.
        for name in _COLUMNS:
            iv: Interval = getattr(self, name)
            if iv.x0 >= iv.x1:
                raise ValueError(
                    f"ColumnLayout.{name}: x0 ({iv.x0}) должен быть < x1 ({iv.x1})"
                )

        for left, right in zip(_COLUMNS, _COLUMNS[1:]):
            lx1 = getattr(self, left).x1
            rx0 = getattr(self, right).x0
            if lx1 > rx0:
                raise ValueError(
                    f"ColumnLayout: {left!r} и {right!r} идут не по порядку "
                    f"или пересекаются ({lx1} > {rx0})"
                )

    def to_dict(self) -> dict[str, dict[str, float]]:
        return {
            name: {"x0": getattr(self, name).x0, "x1": getattr(self, name).x1}
            for name in _COLUMNS
        }

    @classmethod
    def from_dict(cls, data: dict[str, dict[str, float]]) -> "ColumnLayout":
        return cls(**{
            name: Interval(x0=data[name]["x0"], x1=data[name]["x1"])
            for name in _COLUMNS
        })


    @classmethod
    def default(cls) -> "ColumnLayout":
        return cls(
            date=Interval(45, 102),
            time=Interval(102, 152),
            category=Interval(152, 370),
            amount=Interval(370, 462),
            balance=Interval(462, 560),
        )