"""Sentinel-объект «значение не передано» для partial-update API.

Singleton: любой вызов _UnsetType() возвращает ОДИН и тот же объект.
Это позволяет писать `if x is UNSET` вместо `isinstance(x, _UnsetType)`
и гарантирует, что сравнение через `is` всегда корректно.
"""

from __future__ import annotations


class _UnsetType:
    __slots__ = ()

    _instance: "_UnsetType | None" = None

    def __new__(cls) -> "_UnsetType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False

    def __copy__(self) -> "_UnsetType":
        return self

    def __deepcopy__(self, _memo) -> "_UnsetType":
        return self

    def __reduce__(self):
        # pickle: сохраняем singleton при сериализации.
        return (_UnsetType, ())


UNSET = _UnsetType()