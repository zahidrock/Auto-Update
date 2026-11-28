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

    def test_public_community_sources_are_allowed_for_discovery(self):
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

    def test_only_evidenced_free_to_air_streams_are_authorized(self):
        approved = (
            ("ABC News Live 4 (720p)",
             "https://abcnews-streams.akamaized.net/hls/live/2023563/abcnewshudson4/master.m3u8"),
            ("ABC News Live 6 (1080p)",
             "https://abcnews-livestreams.akamaized.net/out/v1/9a9ee355c85a41139f57059aa69e2dbb/abcn-live-06-cmaf-manifest/abcn-live-06-index.m3u8"),
            ("Bloomberg TV Asia Live Event (720p)",
             "https://bloomberg.com/media-manifest/streams/asia-event.m3u8"),
            ("Bloomberg TV Australia (270p)",
             "https://bloomberg.com/media-manifest/streams/aus.m3u8"),
            ("BBC Earth US (1080p)",
             "https://amg00793-amg00793c6-vizio-us-2670.playouts.now.amagi.tv/playlist/amg00793-bbcstudios-bbcearthaall-vizious/playlist.m3u8"),
        )
        for name, url in approved:
            with self.subTest(name=name):
                self.assertTrue(collector.is_authorized_free_to_air_stream(
                    url, name, "English TV",
                    "https://raw.githubusercontent.com/example/list/main/list.m3u"
                ))

        self.assertTrue(collector.is_authorized_free_to_air_stream(
            "https://cdn.example.net/btv.m3u8",
            "BTV",
            "Bangladesh TV",
            "https://btvlive.gov.bd/channel/BTV",
        ))
        self.assertFalse(collector.is_authorized_free_to_air_stream(
            "https://cdn.example.net/unknown.m3u8",
            "Unknown Local TV",
            "Uncategorized",
            "https://raw.githubusercontent.com/example/list/main/list.m3u",
        ))
        self.assertFalse(collector.is_authorized_free_to_air_stream(
            "https://rundle.tv/proxy5.php?src=https://example.net/bbc.m3u8",
            "BBC Earth Romania",
            "English TV",
            "https://raw.githubusercontent.com/example/list/main/list.m3u",
        ))
        self.assertFalse(collector.is_authorized_free_to_air_stream(
            "https://3abn.bozztv.com/3abn2/3abn_live/smil:3abn_live.smil/playlist.m3u8",
            "3ABN English (720p)",
            "English TV",
            "https://raw.githubusercontent.com/example/list/main/list.m3u",
        ))
        self.assertFalse(collector.is_authorized_free_to_air_stream(
            "https://abcnews-streams.akamaized.net/hls/live/2023563/abcnewshudson4/master.m3u8?token=secret",
            "ABC News Live 4 (720p)",
            "English TV",
            "https://raw.githubusercontent.com/example/list/main/list.m3u",
        ))

    def test_public_broadcaster_labels_are_allowed(self):
        for name in ("BTV", "BTV News", "BTV Chattogram", "Sangsad Television",
                     "Bangladesh Television"):
            with self.subTest(name=name):
                self.assertTrue(collector.is_free_to_air_label(name, ""))

    def test_prune_keeps_authorized_community_and_official_sources_only(self):
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
        community_source = "https://raw.githubusercontent.com/example/list/main/list.m3u"
        official_source = "https://btvlive.gov.bd/channel/BTV"
        db.executemany(
            "INSERT INTO channels(id,name,category,normalized_name) VALUES(?,?,?,?)",
            ((1, "ABC News Live 4 (720p)", "English TV", "abcnewslive4"),
             (2, "BTV", "Bangladesh TV", "btv"),
             (3, "Unknown Local TV", "Uncategorized", "unknownlocaltv"),
             (4, "HBO Asia", "Uncategorized", "hboasia")),
        )
        db.executemany(
            "INSERT INTO links(id,channel_id,url,source_url,group_title) VALUES(?,?,?,?,?)",
            ((1, 1, "https://abcnews-streams.akamaized.net/hls/live/2023563/abcnewshudson4/master.m3u8", community_source, ""),
             (2, 2, "https://cdn.example.net/btv.m3u8", official_source, ""),
             (3, 3, "https://cdn.example.net/unknown.m3u8", community_source, ""),
             (4, 4, "https://cdn.example.net/hbo.m3u8", community_source, "")),
        )
        db.executemany("INSERT INTO sources(url) VALUES(?)",
                       ((community_source,), (official_source,)))
        collector.prune_unapproved(db)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM links").fetchone()[0], 2)
        self.assertEqual(
            db.execute("SELECT name FROM channels ORDER BY name").fetchall(),
            [("ABC News Live 4 (720p)",), ("BTV",)],
        )
        self.assertEqual(db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 2)
        db.close()


if __name__ == "__main__":
    unittest.main()
