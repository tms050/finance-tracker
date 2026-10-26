# tests/db/test_timestamps.py
"""created_at / updated_at: server_default=func.now(), onupdate=func.now().

SQLite CURRENT_TIMESTAMP имеет СЕКУНДНУЮ точность. Поэтому проверять
«updated_at изменился после update» через time.sleep(1.1) - медленно
и хрупко. Вместо этого детерминированно ставим updated_at в известное
прошлое значение и проверяем, что UPDATE его перезаписал.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import update

from src.db.models import Account
from tests.db.factories import make_account


def test_created_at_and_updated_at_populated_on_insert(session):
    account = make_account(session)
    session.commit()
    session.refresh(account)

    assert account.created_at is not None
    assert account.updated_at is not None
    assert account.created_at == account.updated_at


def test_updated_at_changes_on_update(session):
    account = make_account(session)
    session.commit()
    session.refresh(account)
    original_created_at = account.created_at
    account_id = account.account_id

    # Детерминированно ставим updated_at в прошлое.
    past = datetime(2020, 1, 1, 12, 0, 0)
    session.execute(
        update(Account)
        .where(Account.account_id == account_id)
        .values(updated_at=past)
    )
    session.commit()
    session.refresh(account)
    assert account.updated_at == past  # sanity: прошлое значение записалось

    account.account_name = "Renamed"
    session.commit()
    session.refresh(account)

    assert account.updated_at > past
    assert account.created_at == original_created_at  # onupdate не трогает created_at


def test_updated_at_stable_on_noop_flush(session):

    account = make_account(session)
    session.commit()
    session.refresh(account)
    original_updated_at = account.updated_at

    session.flush()   # нечего обновлять
    session.commit()
    session.refresh(account)

    assert account.updated_at == original_updated_at