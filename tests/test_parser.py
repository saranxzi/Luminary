import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.parser import KIND_ANIME, KIND_MOVIE, KIND_SHOW, parse_path  # noqa: E402

R = r"C:\Lib"


def p(rel, kind=None, root=R):
    return parse_path(rf"{root}\{rel}", root, kind)


class MovieTests(unittest.TestCase):
    CASES = [
        # (path under library root, forced kind, title, year)
        (r"Movies\500 Days of Summer (2009)  [1080p x265 10bit FS69 Joy].mkv", None, "500 Days of Summer", 2009),
        (r"Movies\Memento.2000.REMASTERED.1080p.BluRay.DDP5.1.x265.10bit-GalaxyRG265.mkv", None, "Memento", 2000),
        (r"Movies\Blade.Runner.2049.2017.1080p.WEB-DL.mkv", None, "Blade Runner 2049", 2017),
        (r"Movies\Heat (1995)\Heat.1995.1080p.mkv", None, "Heat", 1995),
        (r"Movies\Heat (1995)\movie.mkv", None, "Heat", 1995),
        (r"Movies\2001 A Space Odyssey 1968.mkv", None, "2001 A Space Odyssey", 1968),
        # numbers in titles never become episodes in a movie folder
        (r"Films\Ocean's 11 (2001).mkv", KIND_MOVIE, "Ocean's 11", 2001),
        (r"Films\2046 (2004).mkv", KIND_MOVIE, "2046", 2004),
        (r"Films\300.mkv", KIND_MOVIE, "300", None),
        (r"Films\The Office S01E01.mkv", KIND_MOVIE, "The Office S01E01", None),
    ]

    def test_movies(self):
        for rel, kind, title, year in self.CASES:
            with self.subTest(rel):
                r = p(rel, kind)
                self.assertEqual((r.kind, r.title, r.year), (KIND_MOVIE, title, year))

    def test_unlabelled_folder_with_plain_movie(self):
        r = p(r"Downloads\Inception.2010.1080p.mkv")
        self.assertEqual((r.kind, r.title, r.year), (KIND_MOVIE, "Inception", 2010))


class EpisodeTests(unittest.TestCase):
    CASES = [
        # (path, forced kind, kind, title, season, episode, episode_end, absolute)
        (r"Shows\Breaking Bad\Season 02\Breaking.Bad.S02E05.1080p.mkv", None, KIND_SHOW, "Breaking Bad", 2, 5, None, False),
        (r"Shows\Breaking Bad\Season 2\S02 E06 - Peekaboo.mkv", None, KIND_SHOW, "Breaking Bad", 2, 6, None, False),
        (r"Shows\The.Office.US.S01E01.720p.mkv", None, KIND_SHOW, "The Office US", 1, 1, None, False),
        (r"Shows\Friends\Friends 3x14.mkv", None, KIND_SHOW, "Friends", 3, 14, None, False),
        (r"Shows\Lost\Lost.S01E01-E02.Pilot.mkv", None, KIND_SHOW, "Lost", 1, 1, 2, False),
        (r"Shows\Lost\Lost S01E03E04.mkv", None, KIND_SHOW, "Lost", 1, 3, 4, False),
        (r"Shows\Dark\Dark Season 1 Episode 2.mkv", None, KIND_SHOW, "Dark", 1, 2, None, False),
        (r"Shows\Dark\Season 3\03 - Life and Death.mkv", None, KIND_SHOW, "Dark", 3, 3, None, False),
        (r"Shows\Dark\S03\E04.mkv", None, KIND_SHOW, "Dark", 3, 4, None, False),
        (r"Shows\Dark\Season 1\Episode 7.mkv", None, KIND_SHOW, "Dark", 1, 7, None, False),
        (r"Shows\Dark\Specials\Dark - Making Of S00E01.mkv", None, KIND_SHOW, "Dark", 0, 1, None, False),
        (r"Shows\Sherlock (2010)\Season 1\Sherlock 101.mkv", None, KIND_SHOW, "Sherlock", 1, 1, None, False),
        (r"Shows\Severance Season 1\Severance - 03.mkv", None, KIND_SHOW, "Severance", 1, 3, None, False),
        (r"Shows\Planet Earth\01 - From Pole to Pole.mkv", None, KIND_SHOW, "Planet Earth", 1, 1, None, True),
        # anime
        (r"Anime\Bleach [BD] [1080p] [HEVC]\[2004] [Season 1] Bleach\Bleach 001 1080p HEVC 10 bit FLAC.mkv",
         None, KIND_ANIME, "Bleach", 1, 1, None, True),
        (r"Anime\Bleach [BD] [1080p] [HEVC]\[2004] [Season 1] Bleach\Bleach 366 1080p HEVC 10 bit FLAC.mkv",
         None, KIND_ANIME, "Bleach", 1, 366, None, True),
        (r"Anime\Frieren\[SubsPlease] Sousou no Frieren - 07 (1080p) [ABCD1234].mkv",
         None, KIND_ANIME, "Frieren", 1, 7, None, True),
        (r"Anime\Frieren\Season 2\[SubsPlease] Sousou no Frieren - 03v2 (1080p).mkv",
         None, KIND_ANIME, "Frieren", 2, 3, None, False),
        (r"Anime\[Erai-raws] Spy x Family S2 - 05 [1080p].mkv", None, KIND_ANIME, "Spy x Family", 2, 5, None, False),
        (r"Anime\Mob Psycho 100 2nd Season - 04.mkv", None, KIND_ANIME, "Mob Psycho 100", 2, 4, None, False),
        (r"Anime\[Group] Haikyuu [12][1080p].mkv", None, KIND_ANIME, "Haikyuu", 1, 12, None, True),
        # category folder forced by the user, with a season folder directly inside it
        (r"Naruto 001.mkv", KIND_ANIME, KIND_ANIME, "Naruto", 1, 1, None, True),
        # unlabelled folders: strict patterns still find episodes
        (r"Downloads\Severance.S02E03.1080p.mkv", None, KIND_SHOW, "Severance", 2, 3, None, False),
        (r"Downloads\[SubsPlease] Dandadan - 05 (1080p).mkv", None, KIND_ANIME, "Dandadan", 1, 5, None, True),
    ]

    def test_episodes(self):
        for rel, force, kind, title, season, ep, end, absolute in self.CASES:
            with self.subTest(rel):
                r = p(rel, force)
                self.assertEqual((r.kind, r.title, r.season, r.episode, r.episode_end, r.absolute),
                                 (kind, title, season, ep, end, absolute))

    def test_bleach_show_folder(self):
        r = p(r"Anime\Bleach [BD] [1080p] [HEVC]\[2004] [Season 1] Bleach\Bleach 145 1080p HEVC 10 bit FLAC.mkv")
        self.assertTrue(r.show_folder.endswith("Bleach [BD] [1080p] [HEVC]"))
        self.assertEqual(r.year, 2004)

    def test_unnumbered_file_in_series_goes_to_specials(self):
        r = p(r"TV\Severance\Severance - Main Title Sequence.mkv", KIND_SHOW)
        self.assertEqual((r.kind, r.title, r.season, r.episode), (KIND_SHOW, "Severance", 0, None))


class ExtrasTests(unittest.TestCase):
    def test_extras_are_skipped(self):
        for rel in (r"Movies\Heat (1995)\Featurettes\Making of.mkv",
                    r"Movies\Heat (1995)\Behind The Scenes\Robert De Niro.mkv",
                    r"Movies\Heat (1995)\Heat-trailer.mkv",
                    r"Shows\Dark\Extras\Cast interview.mkv",
                    r"Movies\Heat (1995)\Sample\heat-sample.mkv"):
            with self.subTest(rel):
                self.assertIsNone(p(rel))


if __name__ == "__main__":
    unittest.main()
