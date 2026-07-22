from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class ParserConfig(Base):
    __tablename__ = "parser_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    start_url: Mapped[str] = mapped_column(Text, nullable=False)
    pagination_container_selector: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pagination_link_selector: Mapped[str | None] = mapped_column(String(500), nullable=True)
    max_pages: Mapped[int] = mapped_column(Integer, default=1)
    product_link_selector: Mapped[str] = mapped_column(String(500), nullable=False)
    product_description_selector: Mapped[str] = mapped_column(String(500), nullable=False)
    ai_prompt_file: Mapped[str] = mapped_column(String(500), default="prompts/default_product_prompt.txt")
    duplicate_stop_limit: Mapped[int] = mapped_column(Integer, default=10)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=25)
    use_playwright_fallback: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_chat_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("product_url", name="uq_products_product_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_id: Mapped[int] = mapped_column(ForeignKey("parser_configs.id"), nullable=False)
    product_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="new")
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class ParseRun(Base):
    __tablename__ = "parse_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_id: Mapped[int] = mapped_column(ForeignKey("parser_configs.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="running")
    pages_seen: Mapped[int] = mapped_column(Integer, default=0)
    products_seen: Mapped[int] = mapped_column(Integer, default=0)
    products_created: Mapped[int] = mapped_column(Integer, default=0)
    products_skipped_existing: Mapped[int] = mapped_column(Integer, default=0)
    stopped_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
