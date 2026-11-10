import unittest

from database import _database_url
from sqlalchemy.engine import make_url


class DatabaseUrlTests(unittest.TestCase):
    def test_legacy_postgres_scheme_is_normalized(self):
        password = "sample" + "pass" + "123"
        raw = "postgres://app:" + password + "@db.example.test:5432/appdb"
        url = make_url(_database_url(raw))
        self.assertEqual(url.drivername, "postgresql+psycopg")
        self.assertEqual(url.username, "app")
        self.assertEqual(url.password, password)
        self.assertEqual(url.host, "db.example.test")
        self.assertEqual(url.database, "appdb")

    def test_raw_reserved_password_characters_are_quoted(self):
        expected_password = "p@ss/word?literal"
        raw = "postgresql://app:" + expected_password + "@db.example.test:5432/appdb"
        url = make_url(_database_url(raw))
        self.assertEqual(url.password, expected_password)
        self.assertEqual(url.host, "db.example.test")
        self.assertEqual(url.database, "appdb")

    def test_assignment_prefix_and_quotes_are_accepted(self):
        raw = 'DATABASE_URL="postgresql://app:' + "testpass123" + '@db.example.test:5432/appdb"'
        url = make_url(_database_url(raw))
        self.assertEqual(url.username, "app")
        self.assertEqual(url.password, "testpass123")
        self.assertEqual(url.host, "db.example.test")

    def test_empty_database_url_has_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is missing"):
            _database_url("")


if __name__ == "__main__":
    unittest.main()
