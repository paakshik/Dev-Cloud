from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utc_now():
    return datetime.now(timezone.utc)


JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_users_name_nonempty"),
        UniqueConstraint("name", name="uq_users_name"),
        Index("ix_users_joined_on_id", "joined_on", "id"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False, default="individual")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    skills: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    linked_accounts: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    avatar_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    avatar_content_type: Mapped[Optional[str]] = mapped_column(String(120))
    joined_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    projects: Mapped[list["ProjectRecord"]] = relationship(back_populates="owner")


class ProjectRecord(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="ck_projects_title_nonempty"),
        CheckConstraint("length(trim(description)) > 0", name="ck_projects_description_nonempty"),
        Index("ix_projects_created_at_id", "created_at", "id"),
        Index("ix_projects_owner_created_at", "owner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    organization: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_skills: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    pay: Mapped[Optional[str]] = mapped_column(String(200))
    benifits: Mapped[Optional[str]] = mapped_column(Text)
    goal: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    owner: Mapped[UserRecord] = relationship(back_populates="projects")


class MessageRecord(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("length(trim(content)) > 0", name="ck_messages_content_nonempty"),
        Index("ix_messages_sender_timestamp", "sender_id", "timestamp", "id"),
        Index("ix_messages_receiver_timestamp", "receiver_id", "timestamp", "id"),
        Index("ix_messages_status_timestamp", "status", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    receiver_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")


class FeedbackRecord(Base):
    __tablename__ = "feedbacks"
    __table_args__ = (
        CheckConstraint("length(trim(comment)) > 0", name="ck_feedback_comment_nonempty"),
        Index("ix_feedback_user_timestamp", "user_id", "timestamp", "id"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    endorsed_skill: Mapped[Optional[str]] = mapped_column(String(200))


class LinkedAccounts(BaseModel):
    linkedin: Optional[str] = ""
    codeforces: Optional[str] = ""
    github: Optional[str] = ""


class User(BaseModel):
    id: str
    name: str
    type: Optional[str] = "individual"
    title: Optional[str] = ""
    skills: Optional[List[str]] = Field(default_factory=list)
    password: str = Field(exclude=True)
    linked_accounts: Optional[LinkedAccounts] = Field(default_factory=LinkedAccounts)
    avatar_url: Optional[str] = ""
    joined_on: datetime = Field(default_factory=utc_now)
    model_config = ConfigDict(from_attributes=True)


class Project(BaseModel):
    id: str
    title: str
    organization: str
    owner_id: str
    description: str
    skills: Optional[List[str]] = Field(default_factory=list, validation_alias="required_skills", serialization_alias="skills")
    pay: Optional[str] = None
    benifits: Optional[str] = None
    goal: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Message(BaseModel):
    id: str
    sender_id: str
    receiver_id: str
    content: str
    timestamp: datetime = Field(default_factory=utc_now)
    status: Optional[str] = "pending"
    model_config = ConfigDict(from_attributes=True)


class Feedback(BaseModel):
    id: Optional[str] = None
    user_id: str
    author_id: str
    comment: str
    timestamp: datetime = Field(default_factory=utc_now)
    endorsed_skill: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
