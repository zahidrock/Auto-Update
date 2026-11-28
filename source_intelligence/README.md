# Public Free-to-Air TV Source Intelligence

This collector accepts stream URLs only when their provenance can be traced to a broadcaster-controlled website explicitly listed in `config/settings.json`.

## Source discovery
- The seed list currently contains Bangladesh Television's public live pages.
- Public community playlists and GitHub repository searches are intentionally disabled. A public M3U file is not evidence that its streams are authorized.
- Nested playlist references are followed only when they remain on an approved broadcaster-owned source domain.
- External stream/CDN hosts are accepted only when their URLs are published by an approved official source page.
- New countries and categories must not be added until an official, publicly accessible free-to-air source is verified.

## Validation and safety
- Private, loopback, link-local, local-network, credential-bearing, signed, and expiring URLs are rejected.
- Known pay-TV/subscription brands, login-gated, DRM-labelled, and geo-blocked entries are excluded.
- Existing database rows are pruned when their source provenance is no longer approved or their channel label indicates pay-TV.
- The collector never signs in, pays, bypasses DRM, or bypasses geo-restrictions.
- HTTP success alone is not enough: HLS manifest and first segment reachability are checked.
- GitHub Actions runs outside Bangladesh, so speed tests are only a rough filter and cannot guarantee playback on a Bangladesh ISP.

## Files
- `config/settings.json`: approved broadcaster domains, limits, categories, and output settings.
- `config/seeds.txt`: official broadcaster live pages.
- `src/main.py`: source collection, provenance checks, validation, database cleanup, and playlist generation.
- `tests/test_source_policy.py`: source, pay-TV, and signed-URL policy regression tests.
- `output/candidate_stream_report.csv`: public HLS candidates from approved official pages that still need review.
- `output/source_report.csv` and `output/link_health_report.csv`: diagnostics.

## Outputs
- `combined.m3u`: fastest primary approved links.
- `all_fast_sources.m3u`: all fast approved links.
- `backup_slow.m3u`: slower but reachable approved links.
- Category-specific M3U files and `channel_report.csv`.
