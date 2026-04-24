from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, Text, DateTime
from datetime import datetime

class Base(DeclarativeBase):
    pass

class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(default="processing")
    md1: Mapped[str] = mapped_column(Text, nullable=True)
    md2: Mapped[str] = mapped_column(Text, nullable=True)
    md3: Mapped[str] = mapped_column(Text, nullable=True)
    md4: Mapped[str] = mapped_column(Text, nullable=True)
    final_report: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)