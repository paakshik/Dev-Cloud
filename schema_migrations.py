"""Small additive PostgreSQL schema upgrades for existing deployments.

Only additive indexes/constraints are attempted. Existing data and table names
are preserved; invalid historical rows are logged and do not prevent startup.
"""
import logging

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger(__name__)

INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_users_joined_on_id ON collabrun_app.users (joined_on, id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_name ON collabrun_app.users (name)",
    "CREATE INDEX IF NOT EXISTS ix_projects_created_at_id ON collabrun_app.projects (created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS ix_projects_owner_created_at ON collabrun_app.projects (owner_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_messages_sender_timestamp ON collabrun_app.messages (sender_id, timestamp, id)",
    "CREATE INDEX IF NOT EXISTS ix_messages_receiver_timestamp ON collabrun_app.messages (receiver_id, timestamp, id)",
    "CREATE INDEX IF NOT EXISTS ix_messages_status_timestamp ON collabrun_app.messages (status, timestamp)",
    "CREATE INDEX IF NOT EXISTS ix_feedback_user_timestamp ON collabrun_app.feedbacks (user_id, timestamp DESC, id)",
)

CONSTRAINTS = (
    ("users", "ck_users_name_nonempty", "CHECK (length(trim(name)) > 0)"),
    ("projects", "ck_projects_title_nonempty", "CHECK (length(trim(title)) > 0)"),
    ("projects", "ck_projects_description_nonempty", "CHECK (length(trim(description)) > 0)"),
    ("messages", "ck_messages_content_nonempty", "CHECK (length(trim(content)) > 0)"),
    ("feedbacks", "ck_feedback_comment_nonempty", "CHECK (length(trim(comment)) > 0)"),
)


def apply_postgres_additive_migrations(connection):
    if connection.dialect.name != "postgresql":
        return
    for statement in INDEXES:
        try:
            with connection.begin_nested():
                connection.execute(text(statement))
        except DBAPIError as error:
            logger.warning("Could not create additive index (%s); inspect existing data/schema: %s", statement.split(" ON ")[0], error)
    for table, name, expression in CONSTRAINTS:
        try:
            with connection.begin_nested():
                connection.execute(text(
                    f"ALTER TABLE collabrun_app.{table} ADD CONSTRAINT {name} {expression} NOT VALID"
                ))
        except DBAPIError as error:
            # Existing installations may already have these constraints; do not hide other DB errors.
            if "already exists" not in str(error).lower():
                logger.warning("Could not add additive constraint %s: %s", name, error)
