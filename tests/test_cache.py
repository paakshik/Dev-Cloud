import unittest
from unittest.mock import patch

import cache


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.deleted = []
        self.set_calls = []

    def get(self, key):
        return self.data.get(key)

    def setex(self, key, ttl, value):
        self.data[key] = value
        self.set_calls.append((key, ttl))

    def scan_iter(self, match, count):
        prefix = match.removesuffix("*")
        return iter([key for key in list(self.data) if key.startswith(prefix)])

    def delete(self, key):
        self.deleted.append(key)
        self.data.pop(key, None)

    def ping(self):
        return True


class CacheTests(unittest.TestCase):
    def test_json_values_round_trip(self):
        fake = FakeRedis()
        with patch.object(cache, "_client", fake):
            cache.cache_set("stats", {"projects": 2}, ttl=9)
            self.assertEqual(cache.cache_get("stats"), {"projects": 2})
            self.assertEqual(fake.set_calls, [("stats", 9)])

    def test_pattern_invalidation_uses_scan_results(self):
        fake = FakeRedis()
        fake.data = {"projects:list:10:0": "[]", "stats:summary": "{}", "other": "1"}
        with patch.object(cache, "_client", fake):
            cache.invalidate_cache("projects:list:*")
        self.assertEqual(fake.deleted, ["projects:list:10:0"])
        self.assertIn("stats:summary", fake.data)

    def test_cache_errors_are_fail_open(self):
        class BrokenRedis(FakeRedis):
            def get(self, key):
                raise cache.RedisError("redis offline")

            def setex(self, key, ttl, value):
                raise cache.RedisError("redis offline")

        with patch.object(cache, "_client", BrokenRedis()):
            self.assertIsNone(cache.cache_get("anything"))
            cache.cache_set("anything", {"value": 1})


if __name__ == "__main__":
    unittest.main()
