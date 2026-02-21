import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum as SAEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


class EnterpriseType(str, enum.Enum):
    FACTORY = "factory"
    RESEARCH_LAB = "research_lab"
    TRANSPORT_SYSTEM = "transport_system"
    TRADING_POST = "trading_post"
    BANK = "bank"


class EnterpriseStatus(str, enum.Enum):
    ACTIVE = "active"
    STALLED = "stalled"
    ABANDONED = "abandoned"


class Enterprise(Base):
    __tablename__ = "enterprises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enterprise_type: Mapped[str] = mapped_column(
        SAEnum(EnterpriseType, name="enterprise_type"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        SAEnum(EnterpriseStatus, name="enterprise_status"),
        nullable=False,
        default=EnterpriseStatus.ACTIVE,
    )
    # owner = the user_id from user_management_service (no FK across services)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    capital_invested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    members: Mapped[list["EnterpriseRole"]] = relationship(
        "EnterpriseRole", back_populates="enterprise", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="enterprise", cascade="all, delete-orphan"
    )
