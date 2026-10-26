"""Чтение и удаление Statement."""

from src.statements.crud import (
    DeleteStatementResult,
    delete_statement,
    get_statement,
    get_statement_by_file_hash,
    list_statements,
)

__all__ = [
    "DeleteStatementResult",
    "delete_statement",
    "get_statement",
    "get_statement_by_file_hash",
    "list_statements",
]