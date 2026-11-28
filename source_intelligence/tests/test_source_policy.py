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

    def test_public_community_sources_are_allowed(self):
        self.assertTrue(collector.is_approved_source(
            "https://raw.githubusercontent.com/example/list/main/playlist.m3u"
        ))
        self.assertTrue(collector.is_approved_source(
            "https://iptv-org.github.io/iptv/index.m3u"
        ))
        self.assertTrue(collector.is_approved_source(
            "https://btvlive.gov.bd/channel/BTV"
        ))

    def test_private_hosts_and_signed_urls_are_rejected(self):
        with patch.object(collector, "public_host_resolves_globally", return_value=False):
            self.assertFalse(collector.is_approved_source("http://192.168.1.2/list.m3u"))
        for query in (
            "access_token=secret", "X-Amz-Signature=secret",
            "X-Amz-Security-Token=secret", "jwt=secret",
            "hdnts=secret", "auth_key=secret",
        ):
            with self.subTest(query=query):
                self.assertFalse(collector.is_public_candidate(
                    "https://cdn.example.net/live.m3u8?" + query
                ))

    def test_known_pay_tv_brands_are_rejected(self):
        for name in ("HBO Asia", "DAZN Combat", "Disney Channel Latin America",
                     "Discovery Channel", "Canal+ Sport 2"):
            with self.subTest(name=name):
                self.assertFalse(collector.is_free_to_air_label(name, ""))

    def test_public_broadcaster_labels_are_allowed(self):
        for name in ("BTV", "BTV News", "BTV Chattogram", "Sangsad Television",
                     "Bangladesh Television"):
            with self.subTest(name=name):
                self.assertTrue(collector.is_free_to_air_label(name, ""))

    def test_prune_keeps_public_source_and_removes_known_pay_tv(self):
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
        public_source = "https://raw.githubusercontent.com/example/list/main/list.m3u"
        public_url = "https://cdn.example.net/btv.m3u8"
        pay_url = "https://cdn.example.net/hbo.m3u8"
        db.executemany(
            "INSERT INTO channels(id,name,category,normalized_name) VALUES(?,?,?,?)",
            ((1, "BTV", "Bangladesh TV", "btv"),
             (2, "HBO Asia", "Uncategorized", "hboasia")),
        )
        db.executemany(
            "INSERT INTO links(id,channel_id,url,source_url,group_title) VALUES(?,?,?,?,?)",
            ((1, 1, public_url, public_source, ""),
             (2, 2, pay_url, public_source, "")),
        )
        db.execute("INSERT INTO sources(url) VALUES(?)", (public_source,))
        collector.prune_unapproved(db)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM links").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT name FROM channels").fetchall(), [("BTV",)])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
