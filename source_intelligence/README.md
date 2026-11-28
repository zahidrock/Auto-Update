# Public IPTV Source Intelligence

The collector discovers public source pages and playlists, including public GitHub M3U/M3U8 repositories. **Discovery is broad; publication is strict.** A public URL, community playlist entry, or HTTP 200 response is not proof that a stream is licensed or free-to-air.

## Source discovery and publication policy
- Public GitHub repositories, M3U/M3U8 playlists, public indexes, and recursively linked public playlists remain eligible for discovery.
- A stream is exported only when its channel name and stream URL match an explicit authorization rule in `config/settings.json`.
- Every authorization rule records one or more evidence URLs to a broadcaster or official free streaming/FAST provider page that documents public free viewing.
- Community playlist sources may point to an authorized stream; the source repository itself is not treated as proof of licensing.
- Unknown or unverified streams are excluded from the database-backed channel reports and all published playlists until evidence is added to the allowlist.
- Known pay-TV/subscription brands, login-gated, DRM-labelled, and geo-blocked entries are excluded.
- Source and stream hosts must resolve to globally routable public IP addresses. Private, loopback, link-local, local-network, credential-bearing, signed, and expiring URLs are rejected.
- Redirects are checked at every hop. The collector never signs in, pays, bypasses DRM, or bypasses geo-restrictions.

## Validation
- HLS manifest and first-segment reachability are checked.
- Fast, slow, offline, and unvalidated links are tracked separately.
- GitHub Actions runs outside Bangladesh, so speed tests are only a rough filter and cannot guarantee playback on a Bangladesh ISP.
- A free stream may still be region-limited by its broadcaster; the project does not attempt to bypass that restriction.

## Files
- `config/settings.json`: request limits, categories, and evidence-backed free-to-air authorization rules.
- `config/seeds.txt`: public playlist indexes.
- `src/main.py`: source collection, authorization checks, validation, database cleanup, and playlist generation.
- `tests/test_source_policy.py`: discovery, authorization, and URL-safety regression tests.
- `output/source_report.csv` and `output/link_health_report.csv`: diagnostics for sources and authorized streams.
- `output/candidate_stream_report.csv`: quarantined candidates that are not published as playable channels.

## Outputs
- `combined.m3u`: fastest primary links that pass authorization and health checks.
- `all_fast_sources.m3u`: all fast links that pass authorization and health checks.
- `backup_slow.m3u`: slower but reachable links that pass authorization checks.
- Category-specific M3U files and `channel_report.csv` contain only authorized streams.
