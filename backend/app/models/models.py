"""
SQLAlchemy models for the trading platform.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID

from app.db.database import Base


# ── Trade / Order Models ────────────────────────────────────


class TradeRecord(Base):
    __tablename__ = "trade_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(String(64), nullable=False, index=True)
    exchange_order_id = Column(String(64), nullable=True)
    strategy_id = Column(String(128), nullable=True, index=True)
    provider = Column(String(64), nullable=False)

    exchange = Column(String(16), nullable=False)
    trading_symbol = Column(String(64), nullable=False, index=True)
    instrument_token = Column(Integer, nullable=True)

    transaction_type = Column(String(8), nullable=False)  # BUY / SELL
    order_type = Column(String(16), nullable=False)
    product = Column(String(16), nullable=False)
    variety = Column(String(16), nullable=False, default="regular")

    quantity = Column(Integer, nullable=False)
    filled_quantity = Column(Integer, nullable=False, default=0)
    pending_quantity = Column(Integer, nullable=False, default=0)

    price = Column(Float, nullable=True)
    trigger_price = Column(Float, nullable=True)
    average_price = Column(Float, nullable=False, default=0.0)

    status = Column(String(32), nullable=False, index=True)
    status_message = Column(Text, nullable=True)

    placed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    pnl = Column(Float, nullable=True)
    is_mock = Column(Boolean, nullable=False, default=False)

    meta = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_trade_records_placed_at", "placed_at"),
        Index("ix_trade_records_provider_status", "provider", "status"),
    )


# ── Strategy Models ─────────────────────────────────────────


class StrategyRecord(Base):
    __tablename__ = "strategy_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_type = Column(String(128), nullable=False)
    strategy_id = Column(String(128), nullable=False, unique=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)

    params = Column(JSON, nullable=False, default=dict)
    state = Column(String(32), nullable=False, default="idle")

    is_active = Column(Boolean, nullable=False, default=False)
    is_mock = Column(Boolean, nullable=False, default=False)

    total_signals = Column(Integer, nullable=False, default=0)
    total_trades = Column(Integer, nullable=False, default=0)
    winning_trades = Column(Integer, nullable=False, default=0)
    losing_trades = Column(Integer, nullable=False, default=0)
    total_pnl = Column(Float, nullable=False, default=0.0)
    max_drawdown = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_run_at = Column(DateTime, nullable=True)

    instruments = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)


# ── Mock Session Models ─────────────────────────────────────


class MockSession(Base):
    __tablename__ = "mock_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)

    provider = Column(String(64), nullable=False, default="mock")
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=True)

    initial_capital = Column(Float, nullable=False, default=1_000_000.0)
    final_capital = Column(Float, nullable=True)
    total_pnl = Column(Float, nullable=True)
    total_trades = Column(Integer, nullable=False, default=0)

    status = Column(String(32), nullable=False, default="created")  # created, running, completed, failed
    config = Column(JSON, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    strategies = Column(JSON, nullable=True)  # List of strategy configs used
    meta = Column(JSON, nullable=True)


class MockRecording(Base):
    __tablename__ = "mock_recordings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_name = Column(String(256), nullable=False)
    source_provider = Column(String(64), nullable=False)

    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    tick_count = Column(Integer, nullable=False, default=0)
    instruments = Column(JSON, nullable=True)

    storage_path = Column(String(512), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    meta = Column(JSON, nullable=True)


# ── Config Models ────────────────────────────────────────────


class ConfigEntry(Base):
    __tablename__ = "config_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(256), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False)
    value_type = Column(String(32), nullable=False, default="string")
    scope = Column(String(64), nullable=False, default="global")

    description = Column(Text, nullable=True)
    updated_by = Column(String(128), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ConfigAuditLog(Base):
    __tablename__ = "config_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(256), nullable=False, index=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=False)
    changed_by = Column(String(128), nullable=True)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    source = Column(String(32), nullable=True)  # ui, api, yaml, env


# ── Provider Session Models ──────────────────────────────────


class ProviderSession(Base):
    __tablename__ = "provider_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=True)
    access_token = Column(String(512), nullable=True)
    refresh_token = Column(String(512), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    login_time = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    meta = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_provider_sessions_active", "provider", "is_active"),
    )
