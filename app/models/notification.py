from datetime import datetime
from sqlalchemy import Integer, String, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unread"
    )  # unread, read, resolved
    resolution: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # reprint, manual_note
    resolved_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
