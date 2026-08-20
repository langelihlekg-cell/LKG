import uuid
import datetime
from sqlalchemy import (
    Column, String, Text, Numeric, Boolean, Integer, ForeignKey, TIMESTAMP, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class Org(Base):
    __tablename__ = "orgs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    tier = Column(Text, nullable=False, default="standard")
    webhook_secret = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    api_keys = relationship("ApiKey", back_populates="org")
    jobs = relationship("Job", back_populates="org")


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False)
    key_hash = Column(Text, nullable=False, unique=True)
    label = Column(Text)
    revoked_at = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    org = relationship("Org", back_populates="api_keys")


class Batch(Base):
    __tablename__ = "batches"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False)
    job_count = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("batches.id", ondelete="SET NULL"))
    kind = Column(Text, nullable=False, default="generate")  # generate | qc_only
    release_id = Column(Text)
    artist_id = Column(Text)
    cover_art_url = Column(Text)
    tier = Column(Text)
    duration_seconds = Column(Numeric)
    style_preset = Column(Text)
    callback_url = Column(Text)
    metadata_json = Column("metadata", JSONB, default=dict)
    status = Column(Text, nullable=False, default="queued")
    price_usd = Column(Numeric(6, 2))
    square_asset_url = Column(Text)
    vertical_asset_url = Column(Text)
    error_message = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(TIMESTAMP(timezone=True))

    org = relationship("Org", back_populates="jobs")
    qc_reports = relationship("QCReport", back_populates="job")


class QCReport(Base):
    __tablename__ = "qc_reports"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    passed = Column(Boolean, nullable=False)
    checks = Column(JSONB, nullable=False)
    apple_ready = Column(Boolean, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    job = relationship("Job", back_populates="qc_reports")


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    url = Column(Text, nullable=False)
    attempt = Column(Integer, nullable=False, default=0)
    status = Column(Text, nullable=False, default="pending")
    last_error = Column(Text)
    next_attempt_at = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
