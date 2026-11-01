"""ORM models. Only short excerpts, URLs and metadata are stored — never full articles."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="analyst")  # admin | analyst | readonly
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Screening(Base):
    __tablename__ = "screenings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_name: Mapped[str] = mapped_column(String(300), index=True)
    identifiers: Mapped[dict] = mapped_column(JSON, default=dict)
    job_status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|completed|failed
    stage: Mapped[str] = mapped_column(String(64), default="Queued")
    stage_index: Mapped[int] = mapped_column(Integer, default=0)
    provider_runs: Mapped[list] = mapped_column(JSON, default=list)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    name_variants: Mapped[list] = mapped_column(JSON, default=list)
    queries: Mapped[list] = mapped_column(JSON, default=list)
    auto_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # GREEN|AMBER|RED|FAILED
    auto_reasons: Mapped[list] = mapped_column(JSON, default=list)
    incomplete: Mapped[bool] = mapped_column(Boolean, default=False)
    final_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    override_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative_mode: Mapped[str] = mapped_column(String(16), default="rule-based")
    analysis_mode: Mapped[str] = mapped_column(String(16), default="rule-based")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    disposition: Mapped[str | None] = mapped_column(String(32), nullable=True)
    analyst_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_state: Mapped[str] = mapped_column(String(16), default="open")  # open|closed|reopened
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    anonymised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    findings: Mapped[list["Finding"]] = relationship(back_populates="screening", cascade="all, delete-orphan",
                                                     order_by="Finding.rank")


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    screening_id: Mapped[str] = mapped_column(ForeignKey("screenings.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider: Mapped[str] = mapped_column(String(64))
    providers: Mapped[list] = mapped_column(JSON, default=list)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_source: Mapped[str] = mapped_column(String(32), default="snippet")  # snippet|article|official-record
    fetch_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    quotes: Mapped[list] = mapped_column(JSON, default=list)
    corroborating: Mapped[list] = mapped_column(JSON, default=list)
    independent_sources: Mapped[int] = mapped_column(Integer, default=1)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    primary_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    event_status: Mapped[str] = mapped_column(String(40), default="unknown")
    statuses_detected: Mapped[list] = mapped_column(JSON, default=list)
    mitigation: Mapped[list] = mapped_column(JSON, default=list)
    event_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    temporal: Mapped[str | None] = mapped_column(String(16), nullable=True)
    implication: Mapped[str] = mapped_column(String(32), default="unclear")
    implication_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    party: Mapped[str] = mapped_column(String(16), default="direct")
    party_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_level: Mapped[str] = mapped_column(String(24))
    identity_points: Mapped[int] = mapped_column(Integer, default=0)
    identity_evidence: Mapped[list] = mapped_column(JSON, default=list)
    contradictions: Mapped[list] = mapped_column(JSON, default=list)
    credibility_tier: Mapped[int] = mapped_column(Integer, default=4)
    credibility_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    relevance_reasons: Mapped[list] = mapped_column(JSON, default=list)
    material: Mapped[bool] = mapped_column(Boolean, default=False)
    material_reasons: Mapped[list] = mapped_column(JSON, default=list)
    bucket: Mapped[str] = mapped_column(String(24), default="low")  # review|mitigating|low
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_mode: Mapped[str] = mapped_column(String(16), default="rule-based")
    llm: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(24), nullable=True)  # true_match|false_positive|unresolved
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    screening: Mapped[Screening] = relationship(back_populates="findings")


class AuditEntry(Base):
    __tablename__ = "audit_log"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    screening_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class AppConfig(Base):
    __tablename__ = "app_config"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
