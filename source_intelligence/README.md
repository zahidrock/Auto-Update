# Public IPTV Source Intelligence

The collector discovers freely accessible public source pages and playlists, including public GitHub M3U/M3U8 repositories. A public URL is not proof that a stream is licensed or authorized; the project does not label community streams as official or licensed.

## Source discovery
- Public GitHub repositories, M3U/M3U8 playlists, public indexes, and recursively linked public playlists are eligible.
- Source and stream hosts must resolve to globally routable public IP addresses.
- Private, loopback, link-local, local-network, credential-bearing, signed, and expiring URLs are rejected.
- Known pay-TV/subscription brands, login-gated, DRM-labelled, and geo-blocked entries are excluded.
- New links are independently validated; HTTP 200 alone is not enough.
- The collector never signs in, pays, bypasses DRM, or bypasses geo-restrictions.

## Validation
- HLS manifest and first-segment reachability are checked.
- Fast, slow, offline, and unvalidated links are tracked separately.
- GitHub Actions runs outside Bangladesh, so speed tests are only a rough filter and cannot guarantee playback on a Bangladesh ISP.

## Files
- `config/settings.json`: request limits, categories, and output settings.
- `config/seeds.txt`: public playlist indexes.
- `src/main.py`: source collection, URL safety checks, validation, database cleanup, and playlist generation.
- `tests/test_source_policy.py`: public-source and URL-safety regression tests.
- `output/source_report.csv` and `output/link_health_report.csv`: diagnostics.

## Outputs
- `combined.m3u`: fastest primary links that pass the current public-source and health filters.
- `all_fast_sources.m3u`: all fast links that pass the filters.
- `backup_slow.m3u`: slower but reachable links.
- Category-specific M3U files and `channel_report.csv`.
