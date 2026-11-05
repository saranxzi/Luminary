import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import Database  # noqa: E402
from core.scanner import scan  # noqa: E402


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "Media"
        self.db = Database(Path(self.tmp.name) / "t.db")
        files = [
            "Movies/500 Days of Summer (2009)  [1080p x265 10bit FS69 Joy].mkv",
            "Movies/Memento.2000.REMASTERED.1080p.BluRay.DDP5.1.x265.10bit-GalaxyRG265.mkv",
            "Anime/Bleach [BD] [1080p] [HEVC]/[2004] [Season 1] Bleach/Bleach 001 1080p HEVC 10 bit FLAC.mkv",
            "Anime/Bleach [BD] [1080p] [HEVC]/[2004] [Season 1] Bleach/Bleach 002 1080p HEVC 10 bit FLAC.mkv",
            "Anime/Bleach [BD] [1080p] [HEVC]/[2004] [Season 1] Bleach/Bleach 366 1080p HEVC 10 bit FLAC.mkv",
            "Shows/Breaking Bad/Season 1/Breaking.Bad.S01E01.mkv",
            "Shows/Breaking Bad/Season 1/notes.txt",
        ]
        for f in files:
            p = self.root / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")

    def tearDown(self):
        self.db.shutdown()
        self.tmp.cleanup()

    def test_full_then_incremental(self):
        r = scan(self.db, [str(self.root)])
        self.assertEqual((r.total, r.added), (6, 6))
        lib = {m["title"]: m for m in self.db.library()}
        self.assertEqual(set(lib), {"500 Days of Summer", "Memento", "Bleach", "Breaking Bad"})
        self.assertEqual(lib["Bleach"]["kind"], "anime")
        self.assertEqual(lib["Bleach"]["numbering"], "absolute")
        self.assertEqual(lib["Bleach"]["owned"], 3)
        self.assertEqual(lib["Breaking Bad"]["kind"], "show")

        r = scan(self.db, [str(self.root)])
        self.assertEqual((r.added, r.unchanged, r.removed), (0, 6, 0))

        os.remove(self.root / "Movies/Memento.2000.REMASTERED.1080p.BluRay.DDP5.1.x265.10bit-GalaxyRG265.mkv")
        os.remove(self.root / "Anime/Bleach [BD] [1080p] [HEVC]/[2004] [Season 1] Bleach/Bleach 366 1080p HEVC 10 bit FLAC.mkv")
        r = scan(self.db, [str(self.root)])
        self.assertEqual(r.removed, 2)
        lib = {m["title"]: m for m in self.db.library()}
        self.assertNotIn("Memento", lib)
        self.assertEqual(lib["Bleach"]["owned"], 2)



class CategoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "t.db")
        for f in ["Stuff/Naruto/Naruto 001.mkv", "Stuff/Naruto/Naruto 002.mkv",
                  "Films/Ocean's 11 (2001).mkv", "Films/2046 (2004).mkv",
                  "TV/Severance/Severance S01E01.mkv", "TV/Severance/Behind the scenes.mkv"]:
            p = self.root / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")

    def tearDown(self):
        self.db.shutdown()
        self.tmp.cleanup()

    def folders(self):
        return [{"path": str(self.root / "Stuff"), "kind": "anime"},
                {"path": str(self.root / "Films"), "kind": "movie"},
                {"path": str(self.root / "TV"), "kind": "show"}]

    def test_folder_category_wins(self):
        scan(self.db, self.folders())
        lib = {m["title"]: m for m in self.db.library()}
        self.assertEqual(lib["Naruto"]["kind"], "anime")
        self.assertEqual(lib["Naruto"]["owned"], 2)
        # numbers in titles must not turn movies into episodes
        self.assertEqual(lib["Ocean's 11"]["kind"], "movie")
        self.assertEqual(lib["2046"]["kind"], "movie")
        sev = lib["Severance"]
        self.assertEqual(sev["kind"], "show")
        eps = self.db.episodes(sev["id"])
        self.assertEqual(sorted((e["season"], e["number"]) for e in eps), [(0, 1), (1, 1)])
        self.assertEqual([e["title"] for e in eps if e["season"] == 0], ["Behind the scenes"])

    def test_override_reclassifies(self):
        scan(self.db, self.folders())
        naruto = [m for m in self.db.library() if m["title"] == "Naruto"][0]
        scan(self.db, self.folders(), overrides={naruto["folder"]: "show"})
        lib = {m["title"]: m for m in self.db.library()}
        self.assertEqual(lib["Naruto"]["kind"], "show")
        self.assertEqual(lib["Naruto"]["id"], naruto["id"])  # same item, watch state kept

    def test_category_change_refiles_existing_files(self):
        films = [{"path": str(self.root / "Films"), "kind": "anime"}]
        scan(self.db, films)  # wrong category: "Ocean's 11" becomes an anime episode
        self.assertEqual({m["kind"] for m in self.db.library()}, {"anime"})
        films[0]["kind"] = "movie"
        r = scan(self.db, films)  # unchanged files, new category -> re-filed without "forgetting"
        lib = {m["title"]: m for m in self.db.library()}
        self.assertEqual((r.added, r.moved), (0, 2))
        self.assertEqual(lib["Ocean's 11"]["kind"], "movie")
        self.assertEqual(set(lib), {"Ocean's 11", "2046"})

    def test_movie_override_moves_a_single_file(self):
        f = str(self.root / "Films" / "2046 (2004).mkv")
        scan(self.db, self.folders(), overrides={f: "show"})
        kinds = {m["title"]: m["kind"] for m in self.db.library()}
        self.assertEqual(kinds["Ocean's 11"], "movie")
        self.assertNotEqual(kinds.get("2046"), "movie")


if __name__ == "__main__":
    unittest.main()
