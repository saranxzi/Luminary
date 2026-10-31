import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_health  # noqa: E402
from core.db import Database  # noqa: E402


class DbHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "library.db"
        db = Database(self.path)
        mid = db.upsert_media("series:bleach", "anime", "Bleach", 2004, "x")
        for n in (1, 2, 3):
            db.add_file(f"C:/b/{n}.mkv", 1, 1.0, mid, 1, n, absolute=True)
        eps = {e["number"]: e for e in db.episodes(mid)}
        db.set_progress(episode_id=eps[1]["id"], position=1400, duration=1400)
        db.set_progress(episode_id=eps[2]["id"], position=300, duration=1400)
        db.shutdown()

    def tearDown(self):
        self.tmp.cleanup()

    def test_repair_rebuilds_and_keeps_watch_state(self):
        report = db_health.repair(self.path)
        self.assertTrue(report["verified"])
        self.assertTrue(Path(report["aside"], "library.db").exists())  # damaged copy kept
        self.assertTrue(db_health.is_healthy(self.path))
        c = sqlite3.connect(self.path)
        rows = c.execute("SELECT number, watched, position FROM episodes ORDER BY number").fetchall()
        meta = c.execute("SELECT meta_status FROM media").fetchone()[0]
        c.close()
        self.assertEqual(rows, [(1, 1, 0.0), (2, 0, 300.0), (3, 0, 0.0)])
        self.assertEqual(meta, "pending")  # episode guide is re-fetched after a rebuild

    def test_damaged_backup_is_replaced(self):
        out = db_health.backup(self.path, self.dir / "backups")
        out.write_bytes(b"not a database")
        db_health.backup(self.path, self.dir / "backups")
        self.assertTrue(db_health.is_healthy(out))


if __name__ == "__main__":
    unittest.main()
