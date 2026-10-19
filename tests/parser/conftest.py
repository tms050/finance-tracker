"""Общие фикстуры для тестов sber_parser.

- `parser` — чистый экземпляр SberStatementParser (создаётся на тест:
  класс не потокобезопасен и копит warnings).
- `fixtures_dir` — путь к каталогу с эталонными PDF.
- `pdf_path` — параметр, которым pytest автоматически параметризует
  все тесты, запросившие его в сигнатуре. Если PDF-фикстур нет,
  подставляется None, а тест сам делает skip.
"""
from pathlib import Path
from typing import Optional

import pytest

from parser.sber_parser.sber_pdf import SberStatementParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _pdf_paths() -> list[Path]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(FIXTURES_DIR.glob("*.pdf"))


@pytest.fixture
def parser() -> SberStatementParser:
    return SberStatementParser()


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


def pytest_generate_tests(metafunc):
    """Автопараметризация по всем PDF из fixtures/ для тестов,
    которые принимают аргумент `pdf_path`."""
    if "pdf_path" in metafunc.fixturenames:
        paths = _pdf_paths()
        if paths:
            metafunc.parametrize(
                "pdf_path", paths, ids=[p.stem for p in paths]
            )
        else:
            metafunc.parametrize(
                "pdf_path", [None], ids=["no-fixtures"]
            )


@pytest.fixture
def skip_if_no_fixture(pdf_path: Optional[Path]):
    if pdf_path is None:
        pytest.skip("нет PDF-фикстур в fixtures/")
    return pdf_path