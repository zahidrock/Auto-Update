import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import main as collector


class SourcePolicyTests(unittest.TestCase):
    def setUp(self):
        self.dns_patch = patch.object(
            collector, "public_host_resolves_globally", return_value=True
        )
        self.dns_patch.start()

    def tearDown(self):
        self.dns_patch.stop()

    def test_only_approved_broadcaster_domains_are_sources(self):
        self.assertTrue(collector.is_approved_source("https://btvlive.gov.bd/channel/BTV"))
        self.assertTrue(collector.is_approved_source("https://www.btv.gov.bd/"))
        self.assertFalse(collector.is_approved_source(
            "https://raw.githubusercontent.com/example/list/main/playlist.m3u"
        ))
        self.assertFalse(collector.is_approved_source(
            "https://iptv-org.github.io/iptv/index.m3u"
        ))
        self.assertFalse(collector.is_approved_source("https://wavespb.com/"))

    def test_signed_and_credential_urls_are_rejected(self):
        for query in (
            "access_token=secret",
            "X-Amz-Signature=secret",
            "X-Amz-Security-Token=secret",
            "jwt=secret",
            "hdnts=secret",
            "auth_key=secret",
        ):
            with self.subTest(query=query):
                self.assertFalse(
                    collector.is_public_candidate(
                        "https://cdn.example.net/live.m3u8?" + query
                    )
                )

    def test_known_pay_tv_brands_are_rejected(self):
        blocked = (
            "HBO Asia",
            "HBO Xtreme Latin America",
            "Cinemax Asia Taiwan",
            "AXN CEE Romania",
            "FILMBOX+ Emotion Bulgaria",
            "Canal+ Sport 2",
            "Fox Sports News",
            "Eurosport 1 Romania",
            "DAZN Combat",
            "Discovery Channel",
            "Disney Channel Latin America",
        )
        for name in blocked:
            with self.subTest(name=name):
                self.assertFalse(collector.is_free_to_air_label(name, ""))

    def test_public_broadcaster_labels_are_not_blocked_by_name(self):
        for name in ("BTV", "BTV News", "BTV Chattogram", "Sangsad Television"):
            with self.subTest(name=name):
                self.assertTrue(collector.is_free_to_air_label(name, ""))

    def test_prune_removes_community_and_pay_tv_rows(self):
        db = sqlite3.connect(":memory:")
        db.executescript("""
            CREATE TABLE channels(
                id INTEGER PRIMARY KEY, name TEXT, category TEXT, normalized_name TEXT
            );
            CREATE TABLE links(
                id INTEGER PRIMARY KEY, channel_id INTEGER, url TEXT,
                source_url TEXT, group_title TEXT
            );
            CREATE TABLE sources(url TEXT PRIMARY KEY);
            CREATE TABLE candidate_streams(
                url TEXT PRIMARY KEY, source_url TEXT
            );
        """)
        official = "https://btvlive.gov.bd/channel/BTV"
        community = "https://raw.githubusercontent.com/example/list/main/list.m3u"
        db.executemany(
            "INSERT INTO channels(id,name,category,normalized_name) VALUES(?,?,?,?)",
            (
                (1, "BTV", "Bangladesh TV", "btv"),
                (2, "HBO Asia", "Uncategorized", "hboasia"),
                (3, "Community Sports", "Sports", "communitysports"),
            ),
        )
        db.executemany(
            "INSERT INTO links(id,channel_id,url,source_url,group_title) VALUES(?,?,?,?,?)",
            (
                (1, 1, "https://cdn.example.net/btv.m3u8", official, ""),
                (2, 2, "https://cdn.example.net/hbo.m3u8", official, ""),
                (3, 3, "https://cdn.example.net/community.m3u8", community, ""),
            ),
        )
        db.executemany("INSERT INTO sources(url) VALUES(?)", ((official,), (community,)))
        db.executemany(
            "INSERT INTO candidate_streams(url,source_url) VALUES(?,?)",
            (
                ("https://cdn.example.net/official-candidate.m3u8", official),
                ("https://cdn.example.net/community-candidate.m3u8", community),
            ),
        )

        collector.prune_unapproved(db)

        self.assertEqual(db.execute("SELECT COUNT(*) FROM links").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT name FROM channels").fetchall(), [("BTV",)])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM candidate_streams").fetchone()[0], 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
