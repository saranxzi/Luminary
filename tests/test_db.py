import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import Database  # noqa: E402


class DbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.db.shutdown()
        self.tmp.cleanup()

    def _series(self, owned=(1, 2, 3, 5)):
        mid = self.db.upsert_media("series:bleach", "anime", "Bleach", None, "x")
        for n in owned:
            self.db.add_file(f"C:/b/{n}.mkv", 1, 1.0, mid, 1, n, absolute=True)
        self.db.finish_scan()
        return mid

    def test_movie_progress_and_threshold(self):
        mid = self.db.upsert_media("movie:a", "movie", "Memento", 2000, "x")
        self.db.add_file("C:/a.mkv", 1, 1.0, mid)
        self.assertFalse(self.db.set_progress(media_id=mid, position=600, duration=6800))
        m = self.db.media(mid)
        self.assertEqual((m["watched"], m["position"]), (0, 600))
        cw = self.db.continue_watching()
        self.assertEqual(len(cw), 1)
        self.assertAlmostEqual(cw[0]["progress"], 600 / 6800)
        self.assertTrue(self.db.set_progress(media_id=mid, position=6200, duration=6800, threshold=0.9))
        m = self.db.media(mid)
        self.assertEqual((m["watched"], m["position"]), (1, 0))
        self.assertEqual(self.db.continue_watching(), [])
        self.assertEqual(self.db.library()[0]["state"], "watched")

    def test_metadata_adds_missing_episodes_and_keeps_files(self):
        mid = self._series()
        guide = [{"season": 1, "number": n, "title": f"Ep {n}"} for n in range(1, 11)]
        self.db.apply_metadata(mid, {"title": "BLEACH", "overview": "o", "genres": ["Action"]}, guide)
        eps = self.db.episodes(mid)
        self.assertEqual(len(eps), 10)
        self.assertEqual(sum(1 for e in eps if e["file_path"]), 4)
        lib = self.db.library()[0]
        self.assertEqual((lib["owned"], lib["known_eps"], lib["genres"]), (4, 10, ["Action"]))

    def test_next_episode_skips_missing(self):
        mid = self._series()
        self.db.apply_metadata(mid, {}, [{"season": 1, "number": n} for n in range(1, 8)])
        eps = {e["number"]: e for e in self.db.episodes(mid)}
        self.assertEqual(self.db.next_episode(eps[3]["id"])["number"], 5)
        self.assertIsNone(self.db.next_episode(eps[5]["id"]))
        self.assertEqual(self.db.previous_episode(eps[5]["id"])["number"], 3)

    def test_resume_and_continue_watching_series(self):
        mid = self._series()
        eps = {e["number"]: e for e in self.db.episodes(mid)}
        self.assertEqual(self.db.resume_episode(mid)["number"], 1)
        self.db.set_progress(episode_id=eps[1]["id"], position=1300, duration=1400)  # finished
        self.assertEqual(self.db.resume_episode(mid)["number"], 2)
        self.db.set_progress(episode_id=eps[2]["id"], position=100, duration=1400)
        cw = self.db.continue_watching()
        self.assertEqual(len(cw), 1)
        self.assertEqual(cw[0]["episode"]["number"], 2)
        lib = self.db.library(status="in_progress")
        self.assertEqual(len(lib), 1)

    def test_mark_series_watched_and_unwatched(self):
        mid = self._series()
        self.db.set_watched(media_id=mid, watched=True, owned_only=True)
        self.assertEqual(self.db.library()[0]["state"], "watched")
        self.db.set_watched(media_id=mid, watched=False)
        self.assertEqual(self.db.library()[0]["state"], "unwatched")

    def test_removed_file_hides_item_and_prunes_untouched_ones(self):
        kept = self.db.upsert_media("movie:a", "movie", "A", None, "x")
        gone = self.db.upsert_media("movie:b", "movie", "B", None, "x")
        self.db.add_file("C:/a.mkv", 1, 1.0, kept)
        self.db.add_file("C:/b.mkv", 1, 1.0, gone)
        self.db.set_progress(media_id=kept, position=100, duration=1000)
        self.db.remove_files(["C:/a.mkv", "C:/b.mkv"])
        self.db.finish_scan()
        self.assertEqual(self.db.library(), [])
        self.assertEqual(self.db.media(kept)["available"], 0)   # has watch history: kept, hidden
        self.assertIsNone(self.db.media(gone))                  # never watched: pruned

    def test_numbering_follows_files(self):
        mid = self._series()
        self.assertEqual(self.db.media(mid)["numbering"], "absolute")
        self.db.add_file("C:/b/s2e1.mkv", 1, 1.0, mid, 2, 1, absolute=False)
        self.db.finish_scan()
        self.assertEqual(self.db.media(mid)["numbering"], "seasons")


if __name__ == "__main__":
    unittest.main()
