"""Key/value app settings persisted in the database.

Currency/timezone come from environment config by default; this service
allows the user to override them at runtime (stored in ``app_settings``).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.database.models import AppSetting


class RuntimeSettings:
    """Effective settings: env values, overridden by stored app_settings rows.

    After :meth:`load`, stored overrides win over the env defaults.
    Before :meth:`load`, the env defaults are returned.
    """

    def __init__(self, base: Optional[Settings] = None):
        self._base = base or get_settings()
        self._currency: Optional[str] = None
        self._timezone: Optional[str] = None
        self._low_stock_notifications: bool = True

    async def load(self, db: AsyncSession) -> "RuntimeSettings":
        rows = (
            await db.execute(select(AppSetting.key, AppSetting.value))
        ).all()
        override = dict(rows)
        self._currency = (override.get("currency") or "").strip() or self._base.currency
        self._timezone = (override.get("timezone") or "").strip() or self._base.timezone
        self._low_stock_notifications = (
            override.get("low_stock_notifications") or "true"
        ).lower() != "false"
        return self

    def currency(self) -> str:
        return self._currency or self._base.currency

    def timezone(self) -> str:
        return self._timezone or self._base.timezone

    def low_stock_notifications(self) -> bool:
        return self._low_stock_notifications

    async def set(self, db: AsyncSession, key: str, value: Optional[str]) -> None:
        """Upsert one setting. Empty/None value clears the stored override."""
        row = (
            await db.execute(select(AppSetting).where(AppSetting.key == key))
        ).scalar_one_or_none()
        value = (value or "").strip() or None

        if row is None:
            if value is not None:
                db.add(AppSetting(key=key, value=value))
            await db.commit()
            return

        if value is None:
            db.delete(row)
        else:
            row.value = value
        await db.commit()


def make_runtime_settings() -> RuntimeSettings:
    """Create a RuntimeSettings from env config (call ``load`` with a session)."""
    return RuntimeSettings()
