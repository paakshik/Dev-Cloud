import os
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "postgresql://invalid:[REDACTED]@127.0.0.1:1/test")
os.environ["REDIS_URL"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from database import Base, get_db
from main import app, password_context
from models import FeedbackRecord, MessageRecord, ProjectRecord, UserRecord


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        ).execution_options(schema_translate_map={"collabrun_app": None})
        cls.SessionTesting = sessionmaker(bind=cls.engine, autoflush=False, autocommit=False)
        Base.metadata.create_all(cls.engine)

        def override_get_db():
            session = cls.SessionTesting()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(cls.engine)
        cls.engine.dispose()

    def setUp(self):
        with self.SessionTesting() as session:
            session.query(FeedbackRecord).delete()
            session.query(MessageRecord).delete()
            session.query(ProjectRecord).delete()
            session.query(UserRecord).delete()
            session.commit()
            session.add_all([
                UserRecord(id="owner", name="Owner", password=password_context.hash("owner-pass"), skills=["Python"], linked_accounts={}, avatar_url=""),
                UserRecord(id="member", name="Member", password=password_context.hash("member-pass"), skills=["Design"], linked_accounts={}, avatar_url=""),
            ])
            session.commit()

    def test_user_signup_login_and_secret_not_returned(self):
        response = self.client.post("/api/v1/users", json={"id": "new-user", "name": "New User", "password": "new-pass"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("password", response.json())
        self.assertEqual(self.client.post("/api/v1/login", data={"username": "New User", "password": "new-pass"}).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/login", data={"username": "New User", "password": "wrong"}).status_code, 401)

    def test_project_creation_and_stats(self):
        response = self.client.post("/api/v1/projects", json={"title": "Build a tool", "description": "A project", "owner_id": "owner", "skills": ["Python"], "benefits": "Portfolio"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["skills"], ["Python"])
        self.assertEqual(response.json()["benifits"], "Portfolio")
        self.assertEqual(self.client.get("/api/v1/stats").json()["projects"], 1)

    def test_project_requires_existing_owner(self):
        response = self.client.post("/api/v1/projects", json={"title": "Bad project", "description": "No valid owner", "owner_id": "missing"})
        self.assertEqual(response.status_code, 400)

    def test_message_round_trip_and_status_update(self):
        payload = {"id": "msg-1", "sender_id": "member", "receiver_id": "owner", "content": "I would like to help", "status": "pending"}
        created = self.client.post("/api/v1/messages", json=payload)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(len(self.client.get("/api/v1/messages", params={"user_id": "member"}).json()), 1)
        updated = self.client.put("/api/v1/messages/msg-1", json="accepted")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["status"], "accepted")

    def test_feedback_create_update_delete(self):
        created = self.client.post("/api/v1/feedbacks", json={"user_id": "member", "author_id": "owner", "comment": "Thoughtful teammate"})
        self.assertEqual(created.status_code, 200)
        feedback_id = created.json()["id"]
        updated = self.client.put(f"/api/v1/feedbacks/{feedback_id}", json={"id": feedback_id, "user_id": "member", "author_id": "owner", "comment": "Updated note"})
        self.assertEqual(updated.json()["comment"], "Updated note")
        deleted = self.client.delete(f"/api/v1/feedbacks/{feedback_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/feedbacks/member").json(), [])

    def test_avatar_upload_is_saved_and_served_from_database(self):
        response = self.client.put("/api/v1/users/member", data={"name": "Member", "title": "Designer", "skills": '["Design"]', "linked_accounts": "{}"}, files={"avatar": ("avatar.png", b"test-avatar", "image/png")})
        self.assertEqual(response.status_code, 200)
        avatar = self.client.get("/api/v1/users/member/avatar")
        self.assertEqual(avatar.content, b"test-avatar")
        self.assertEqual(avatar.headers["content-type"], "image/png")

    def test_users_and_projects_are_paginated(self):
        for index in range(4):
            self.client.post("/api/v1/projects", json={"title": f"Project {index}", "description": "Page test", "owner_id": "owner"})
        users = self.client.get("/api/v1/users", params={"limit": 1, "offset": 0})
        self.assertEqual(users.status_code, 200)
        self.assertEqual(len(users.json()), 1)
        projects = self.client.get("/api/v1/projects", params={"limit": 2, "offset": 1})
        self.assertEqual(projects.status_code, 200)
        self.assertEqual(len(projects.json()), 2)
        self.assertEqual(self.client.get("/api/v1/projects", params={"limit": 101}).status_code, 422)

    def test_cache_hit_and_mutation_invalidates_cached_lists(self):
        import main as main_module
        from unittest.mock import patch

        with patch.object(main_module, "cache_get", side_effect=[None, [{"id": "cached", "name": "Cached"}]]), patch.object(main_module, "cache_set") as cache_set:
            first = self.client.get("/api/v1/users")
            second = self.client.get("/api/v1/users")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json()[0]["id"], "cached")
        cache_set.assert_called_once()

        with patch.object(main_module, "invalidate_cache") as invalidate:
            response = self.client.post("/api/v1/users", json={"id": "invalidate-me", "name": "Invalidate", "password": "secret"})
        self.assertEqual(response.status_code, 200)
        invalidate.assert_called_once_with("users:list:*", "stats:*")


if __name__ == "__main__":
    unittest.main()
