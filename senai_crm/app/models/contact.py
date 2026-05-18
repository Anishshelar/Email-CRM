from sqlalchemy import Column, Integer, String, Float, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.enums import ContactStatus


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=True)
    company = Column(String, nullable=True)
    status = Column(Enum(ContactStatus), nullable=False, default=ContactStatus.ACTIVE)

    # DISPLAY FIELD ONLY — not for currency arithmetic. Use a ledger table if
    # billing calculations are ever required.
    account_value = Column(Float, nullable=True)

    churn_risk_score = Column(Float, nullable=True)  # 0.0 (safe) to 1.0 (high risk)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_contact_at = Column(DateTime(timezone=True), nullable=True)

    threads = relationship("Thread", back_populates="contact")
