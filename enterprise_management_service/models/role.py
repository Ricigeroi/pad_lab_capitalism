import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


class RoleType(str, enum.Enum):
    INVENTOR = "inventor"
    STRATEGIST = "strategist"
    INDUSTRIALIST = "industrialist"
    OPERATOR = "operator"


class EnterpriseRole(Base):
    __tablename__ = "enterprise_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    enterprise_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("enterprises.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # user_id references user_management_service — no cross-DB FK
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    role: Mapped[str] = mapped_column(
        SAEnum(RoleType, name="role_type"), nullable=False, default=RoleType.OPERATOR
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    enterprise: Mapped["Enterprise"] = relationship("Enterprise", back_populates="members")  # type: ignore[name-defined]
