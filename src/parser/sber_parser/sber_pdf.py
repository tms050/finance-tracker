import re
import logging
import pdfplumber
from typing import Optional


from .config import ParserConfig, ColumnLayout
from .models import StatementInfo, Transaction, BalanceCheck, ParseResult, BalanceStatus
from .counterparty import extract_person_name
from .dates import (parse_date, parse_time, DATE_RE, TIME_RE)
from .amount import (parse_amount_to_kopecks, parse_balance_to_kopecks, normalize_currency)

# ============================================================
#  ПАРСЕР
# ============================================================

_CURRENCY_STOP_WORDS = frozenset({
    # правая колонка «ИТОГО ПО ОПЕРАЦИЯМ ЗА ПЕРИОД»
    "остаток", "пополнение", "списание", "итого", "на",
    # левый столбец реквизитов
    "дата", "номер", "карта", "владелец", "валюта",
})

class SberStatementParser:
    """Парсер выписки Сбера (формат на 01.10.2026).

    Пример:
        parser = SberStatementParser()
        result = parser.parse("statement.pdf")
        for tx in result.transactions:
            print(tx.date, tx.amount)
    """

    def __init__(self, config: Optional[ParserConfig] = None,
                 layout: Optional[ColumnLayout] = None,
                 logger: Optional[logging.Logger] = None):
        self.cfg = config or ParserConfig()
        self._layout = layout
        self.log = logger or logging.getLogger(__name__)
        self._warnings: list[str] = []

    # ---------- публичный метод ----------

    def parse(self, path: str) -> ParseResult:
        self._warnings = []
        try:
            with pdfplumber.open(path) as pdf:

                if not pdf.pages:
                    raise ValueError(f"PDF не содержит страниц: {path}")
                
                statement = self._extract_statement_info(pdf.pages[0])
                layout = self._layout or self._find_column_layout(pdf)
                raw = []
                for page in pdf.pages:
                    raw.extend(self._parse_page(page, layout))

            currency = normalize_currency(statement.currency)
            transactions = [self._normalize(t, currency) for t in raw]
            check = self._validate_balance(transactions)

            return ParseResult(
                statement=statement,
                transactions=transactions,
                balance_check=check,
                warnings=list(self._warnings),
            )
        except Exception as e:
            self.log.error(f"Не удалось открыть или прочитать PDF: {e}")
            self._warnings.append(f"Ошибка чтения PDF: {e}")
            return ParseResult(statement=StatementInfo(), warnings=self._warnings) 

    # =========================================================
    #  Определение границ колонок
    # =========================================================

    def _find_column_layout(self, pdf) -> ColumnLayout:
        """Определяет границы колонок по ряду 1 шапки.

        Ищет страницу с шапкой (маркер "код авторизации"), затем строку-якоря
        выше неё. При неудаче - ColumnLayout.default() + warning.
        """
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["fontname"])
            lines = self._group_into_lines(words)
            h = self._find_header_end(lines, page.height)
            if h < 0:
                continue
            layout = self._build_layout_from_lines(lines, h, page)
            if layout is not None:
                return layout

        self._warn("не удалось определить границы колонок из шапки, использую `по умолчанию`")
        return ColumnLayout.default()

    def _build_layout_from_lines(self, lines, header_end: int, page) -> Optional[ColumnLayout]:
        # ряд 1 шапки - ближайшая строка выше маркера, где есть все 4 якоря (uppercase)
        row = None
        for i in range(header_end - 1, -1, -1):
            tokens = {w["text"] for w in lines[i]}
            if all(a in tokens for a in self.cfg.header_anchor_words):
                row = lines[i]
                break
        if row is None:
            return None

        by_text = {w["text"]: w for w in row}
        x0_date = by_text["ДАТА"]["x0"]
        x0_cat  = by_text["КАТЕГОРИЯ"]["x0"]
        x0_sum  = by_text["СУММА"]["x0"]
        x0_ost  = by_text["ОСТАТОК"]["x0"]

        # правый край: "СЧЁТА" (последнее слово заголовка суммы) и "СРЕДСТВ"
        amount_words  = [w for w in row if x0_sum <= w["x0"] < x0_ost]
        balance_words = [w for w in row if w["x0"] >= x0_ost]
        if not amount_words or not balance_words:
            return None
        x1_amount  = max(w["x1"] for w in amount_words)
        x1_balance = max(w["x1"] for w in balance_words)

        # граница времени
        x_time = self._find_time_boundary(page, header_end)
        if x_time is None:
            x_time = x0_date + self.cfg.time_boundary_ratio * (x0_cat - x0_date)

        return ColumnLayout(
            date=(x0_date, x_time),
            time=(x_time, x0_cat),
            category=(x0_cat, x0_sum),
            amount=(x0_sum, x1_amount),
            balance=(x1_amount, x1_balance),
        )

    def _find_time_boundary(self, page, header_end: int) -> Optional[float]:
        """min x0 токенов 'HH:MM' между шапкой и футером."""
        words = page.extract_words()
        lines = self._group_into_lines(words)

        footer_y = self._find_footer_y(page, lines)
        body = lines[header_end + 1:]
        if footer_y is not None:
            body = [lw for lw in body if min(w["top"] for w in lw) < footer_y]

        xs = [
            w["x0"]
            for lw in body
            for w in lw
            if TIME_RE.match(w["text"])
        ]
        return min(xs) if xs else None

    @staticmethod    
    def _clean_currency_value(tokens: list[str]) -> str:
        """Склеивает токены после метки «Валюта», пока не упрёмся в стоп-слово
        или число. Числа отсекают правую колонку с суммами и датами,
        стоп-слова — её заголовки."""
        words: list[str] = []
        for t in tokens:
            low = t.lower().rstrip(".,:;")
            if low in _CURRENCY_STOP_WORDS:
                break
            if any(ch.isdigit() for ch in t):
                break
            words.append(t)
        return " ".join(words).strip()

    # =========================================================
    #  Информация о счёте
    # =========================================================

    def _extract_statement_info(self, page) -> StatementInfo:
        words = page.extract_words(
            keep_blank_chars=False,
            use_text_flow=False,
            extra_attrs=["size", "fontname"],
        )
        lines = self._group_into_lines(words)
        line_tokens = [[w["text"] for w in lw] for lw in lines]

        def norm(t: str) -> str:
            return t.strip(" .,:;").lower()

        normalized = [[norm(t) for t in tokens] for tokens in line_tokens]

        # неякорный regex для поиска дат внутри строки
        date_inline_re = re.compile(r"\d{2}\.\d{2}\.\d{4}")

        def find_by_prefix(prefix: list[str]) -> Optional[int]:
            prefix_l = [p.lower() for p in prefix]
            n = len(prefix_l)
            for i, tokens in enumerate(normalized):
                if tokens[:n] == prefix_l:
                    return i
            return None

        fio = None
        account_number_masked = None
        card_number_masked = None
        currency = None
        period_start = None
        period_end = None
        open_date = None
        close_date = None

        # Период
        for i, tokens in enumerate(normalized):
            if "период" in tokens:
                joined = " ".join(line_tokens[i])
                dates = date_inline_re.findall(joined)
                if len(dates) >= 2:
                    period_start = parse_date(dates[0])
                    period_end = parse_date(dates[1])
                    break

        # ФИО
        for label in (["владелец", "счёта"], ["владелец", "счета"]):
            i = find_by_prefix(label)
            if i is not None and i + 1 < len(line_tokens):
                fio = " ".join(line_tokens[i + 1]).strip()
                break

        # Номер счёта
        for label in (["номер", "счёта"], ["номер", "счета"]):
            i = find_by_prefix(label)
            if i is not None and len(line_tokens[i]) > len(label):
                rest = line_tokens[i][len(label):]
                account_number_masked = " ".join(rest).strip()
                break

        # Карта
        i = find_by_prefix(["карта"])
        if i is not None and len(line_tokens[i]) > 1:
            card_number_masked = line_tokens[i][-1]

        i = find_by_prefix(["валюта"])
        if i is not None and len(line_tokens[i]) > 1:
            currency = self._clean_currency_value(line_tokens[i][1:])

        # Даты открытия / закрытия
        for field_name, labels in (
            ("open_date",  (["дата", "открытия", "счёта"],
                            ["дата", "открытия", "счета"],
                            ["дата", "открытия"])),
            ("close_date", (["дата", "закрытия", "счёта"],
                            ["дата", "закрытия", "счета"],
                            ["дата", "закрытия"])),
        ):
            for label in labels:
                i = find_by_prefix(label)
                if i is not None:
                    joined = " ".join(line_tokens[i])
                    dates = date_inline_re.findall(joined)
                    if dates:
                        parsed = parse_date(dates[-1])
                        if parsed:
                            if field_name == "open_date":
                                open_date = parsed
                            else:
                                close_date = parsed

        return StatementInfo(
            fio=fio,
            account_number_masked=account_number_masked,
            card_number_masked=card_number_masked,
            currency=currency,
            period_start=period_start,
            period_end=period_end,
            open_date=open_date,
            close_date=close_date,
        )

    # =========================================================
    #  Границы таблицы
    # =========================================================

    def _find_header_end(self, lines, page_height: float) -> int:
        for i, lw in enumerate(lines):
            if min(w["top"] for w in lw) > page_height * self.cfg.header_search_limit:
                break
            txt = " ".join(w["text"].lower() for w in lw)
            if self.cfg.header_marker in txt:
                return i
        return -1

    def _find_footer_y_from_text(self, lines) -> Optional[float]:
        candidates = []
        for lw in lines:
            txt = " ".join(w["text"].lower() for w in lw)
            if any(p in txt for p in self.cfg.footer_phrases):
                candidates.append(min(w["top"] for w in lw))
        return min(candidates) if candidates else None

    def _find_footer_y_from_shapes(self, page, y_hint: Optional[float]) -> Optional[float]:
        rects = list(getattr(page, "rects", []))
        curves = list(getattr(page, "curves", []))
        window = self.cfg.shape_window
        candidates = []
        for obj in rects + curves:
            top = obj["top"]
            if y_hint is not None and not (y_hint - window <= top <= y_hint + window):
                continue
            for key in ("non_stroking_color", "stroking_color"):
                if self._is_blue(obj.get(key)):
                    candidates.append(top)
                    break
        return min(candidates) if candidates else None

    def _find_footer_y(self, page, lines) -> Optional[float]:
        text_y = self._find_footer_y_from_text(lines)
        shape_y = self._find_footer_y_from_shapes(page, y_hint=text_y)
        candidates = [y for y in (text_y, shape_y) if y is not None]
        return min(candidates) if candidates else None

    # =========================================================
    #  Страница и записи
    # =========================================================

    def _parse_page(self, page, layout: ColumnLayout) -> list[Transaction]:
        words = page.extract_words(extra_attrs=["fontname"])
        lines = self._group_into_lines(words)

        h = self._find_header_end(lines, page.height)
        if h < 0:
            self.log.debug(
                "страница %s: шапка таблицы не найдена, страница пропущена",
                page.page_number,
            )
            return []

        footer_y = self._find_footer_y(page, lines)
        if footer_y is not None:
            body = [lw for lw in lines[h + 1:]
                    if min(w["top"] for w in lw) < footer_y]
        else:
            self.log.debug(f"footer не найден на странице page_number={page.page_number}")
            body = lines[h + 1:]

        return [self._parse_record(r, layout) for r in self._split_into_records(body, layout) if r]

    def _split_into_records(self, body_lines, layout: ColumnLayout):
        records, current = [], []
        for lw in body_lines:
            if self._is_record_start(lw, layout):
                if current:
                    records.append(current)
                current = [lw]
            elif current:
                current.append(lw)
        if current:
            records.append(current)
        return records

    def _is_record_start(self, line_words, layout: ColumnLayout) -> bool:
        date_words = self._words_in(line_words, layout.date)
        has_date = any(DATE_RE.match(w["text"]) for w in date_words)
        if not has_date:
            return False
        return True 

    def _parse_record(self, record_lines, layout: ColumnLayout) -> Transaction:
        main = record_lines[0]
        details = [w for lw in record_lines[1:] for w in lw]

        auth_tokens = [
            w["text"]
            for w in self._words_in(details, layout.time)
            if self.cfg.auth_re.match(w["text"])
        ]

        return Transaction(
            date=self._text_of(main, layout.date),
            time=self._text_of(main, layout.time),
            auth=auth_tokens[0] if auth_tokens else None,
            category=self._text_of(main, layout.category),
            description=self._text_of(details, layout.category),
            amount_raw=self._text_of(main, layout.amount),
            balance_raw=self._text_of(main, layout.balance),
        )

    # =========================================================
    #  Нормализация и валидация
    # =========================================================

    def _normalize(self, tx: Transaction, currency: str) -> Transaction:
        description = (tx.description or "").strip()

        match = self.cfg.transfer_bank_re.match(description)
        if match:
            counterparty_name = match.group(1).strip()
        else:
            counterparty_name = (
                extract_person_name(description)
                or (self.cfg.first_sentence_re.match(description) or [None, None])[1]
            )
        
        currency_norm = normalize_currency(currency)

        return Transaction(
            date=parse_date(tx.date),
            time=parse_time(tx.time),
            auth=tx.auth,
            category=tx.category,
            description=tx.description,
            counterparty_name=counterparty_name,
            currency=currency_norm,
            amount_raw=tx.amount_raw,
            balance_raw=tx.balance_raw,
            amount=parse_amount_to_kopecks(tx.amount_raw),
            balance=parse_balance_to_kopecks(tx.balance_raw),
        )
        
    def _validate_balance(self, records: list[Transaction]) -> BalanceCheck:
        """
        Сверка: oldest_balance + sum(amounts[:-1]) == newest_balance. 
        У Сбера транзакции идут сверху вниз от новых к старым, а в колонке баланса - остаток ПОСЛЕ операции.
            Итоговый статус (по убыванию приоритета):
            INSUFFICIENT_DATA - меньше двух валидных записей;
            MISMATCH - суммы не сошлись;
            INCOMPLETE - сошлись, но часть записей пропущена;
            OK - всё сошлось и пропусков нет.
        """
    
        valid = [r for r in records if r.amount is not None and r.balance is not None]
        skipped = len(records) - len(valid)

        check = BalanceCheck(
            n_records=len(valid),
            n_total_records=len(records),
            n_skipped=skipped,
        )

        if skipped:
            self._error(
                f"сверка баланса: пропущено {skipped} из {len(records)} записей "
                f"(не распознаны amount/balance) — результат ненадёжен"
            )

        if len(valid) < 2:
            # Меньше двух записей — сверять нечего. Статус уже INSUFFICIENT_DATA
            # по умолчанию, ok=False; выходим.
            return check

        oldest, newest = valid[-1], valid[0]
        amounts = [r.amount for r in valid]
        # Эффект самой старой операции уже «сидит» в oldest.balance,
        # поэтому суммируем все, кроме неё.
        total = sum(amounts[:-1])

        expected_newest = oldest.balance + total
        diff = expected_newest - newest.balance

        check.oldest_balance = oldest.balance
        check.newest_balance = newest.balance
        check.sum_amounts = total
        check.expected_newest = expected_newest
        check.diff = diff

        if diff != 0:
            check.status = BalanceStatus.MISMATCH
            check.ok = False
            self._warn(
                f"расхождение баланса: {diff:+d} коп. ({diff / 100:+.2f} руб.)"
            )
        elif skipped:
            # Арифметика сошлась, но часть записей выпала — доверять нельзя.
            check.status = BalanceStatus.INCOMPLETE
            check.ok = False
        else:
            check.status = BalanceStatus.OK
            check.ok = True

        return check

    # =========================================================
    #  Низкоуровневые утилиты
    # =========================================================

    def _group_into_lines(self, words, tol: Optional[int] = None):
        tol = tol or self.cfg.line_tolerance
        if not words:
            return []

        sorted_words = sorted(words, key=lambda w: w["top"])
        lines: list[list[dict]] = []
        current = [sorted_words[0]]
        anchor_top = sorted_words[0]["top"]

        for w in sorted_words[1:]:
            if w["top"] - anchor_top <= tol:
                current.append(w)
            else:
                lines.append(sorted(current, key=lambda x: x["x0"]))
                current = [w]
                anchor_top = w["top"]

        lines.append(sorted(current, key=lambda x: x["x0"]))
        return lines

    @staticmethod
    def _words_in(line_words, x_range):
        x0, x1 = x_range
        return [w for w in line_words if x0 <= w["x0"] < x1]

    def _text_of(self, line_or_words, x_range) -> str:
        if line_or_words and isinstance(line_or_words[0], dict) and "x0" in line_or_words[0]:
            ws = line_or_words
        else:
            ws = [w for lw in line_or_words for w in lw]
        return " ".join(w["text"] for w in self._words_in(ws, x_range))

    @staticmethod
    def _is_bold(word) -> bool:
        return "Bold" in word.get("fontname", "")

    @staticmethod
    def _is_blue(color, min_b=0.2, min_diff=0.15) -> bool:
        if not color or not isinstance(color, (tuple, list)) or len(color) < 3:
            return False
        r, g, b = color[:3]
        if max(r, g, b) > 1.5:
            r, g, b = r / 255, g / 255, b / 255
        return b > min_b and (b - r) > min_diff and (b - g) > min_diff / 2

    def _warn(self, msg: str) -> None:
        self._warnings.append(msg)
        self.log.warning(msg)

    def _error(self, msg: str) -> None:
        self._warnings.append(msg)
        self.log.error(msg)