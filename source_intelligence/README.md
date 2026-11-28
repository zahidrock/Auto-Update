# Public IPTV Source Intelligence

This collector discovers publicly accessible IPTV playlist sources, including GitHub repositories, community M3U/M3U8 indexes, and recursively linked public playlists.

## Source discovery
- Public community indexes are seeded from iptv-org and Free-TV.
- GitHub's public repository search is used to discover additional repositories containing M3U/M3U8 files.
- Nested playlist references are followed up to the configured recursion depth.
- Stream hosts are not restricted to broadcaster-owned domains. Any globally reachable public stream host may be tested.
- Source index hosts remain restricted to known public GitHub Pages / raw GitHub hosts to keep source fetching controlled.

## Validation and safety
- Every stream URL, redirect, and HLS segment is checked for a globally routable public host.
- Private, loopback, link-local, local-network, credential-bearing, and signed/expiring URLs are rejected.
- Obvious subscription, login, geo-block, pay-TV, and DRM-labelled entries are excluded.
- A publicly reachable URL is not proof of copyright permission. Only publicly accessible, free-to-access streams are collected; no login, payment, DRM, or geo-restriction bypass is attempted.
- HTTP success alone is not enough: HLS manifest and first segment reachability are checked.
- GitHub Actions runs outside Bangladesh, so speed tests are only a rough filter and cannot guarantee playback on a Bangladesh ISP.

## Files
- `config/settings.json`: source hosts, limits, categories, and output settings.
- `config/seeds.txt`: public playlist indexes.
- `src/main.py`: GitHub discovery, recursive source collection, validation, database, and playlist generation.
- `output/candidate_stream_report.csv`: public HLS candidates that still need validation.
- `output/source_report.csv` and `output/link_health_report.csv`: diagnostics.

## Outputs
- `combined.m3u`: fastest primary links.
- `all_fast_sources.m3u`: all fast validated links.
- `backup_slow.m3u`: slower but reachable links.
- Category-specific M3U files and `channel_report.csv`.
