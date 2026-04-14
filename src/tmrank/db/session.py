from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tmrank.settings import get_settings


def make_engine(echo: bool = False):
    settings = get_settings()
    return create_engine(settings.database_url, future=True, echo=echo)


def get_session() -> Iterator[Session]:
    session = sessionmaker(bind=make_engine(), expire_on_commit=False, future=True)()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = sessionmaker(bind=make_engine(), expire_on_commit=False, future=True)()
    try:
        yield session
    finally:
        session.close()
