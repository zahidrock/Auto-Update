# Public Free-to-Air TV Source Intelligence

Automated discovery and validation of publicly accessible streams published by approved broadcaster-owned websites.

## Automation
- Runs daily in GitHub Actions.
- Runs after source/config/code changes on `main`.
- Manual run: **Actions → IPTV Source Intelligence → Run workflow**.
- No local PC is required.

## Source policy
- Only broadcaster-controlled source domains listed in `source_intelligence/config/settings.json` are accepted.
- A stream hosted on an external CDN is accepted only when it is directly published by an approved official broadcaster page.
- Public GitHub repositories, community M3U lists, and public reachability alone are not proof of permission; they are not accepted as source authority.
- Known pay-TV/subscription brands, login-gated, DRM-labelled, geo-blocked, signed, expiring, and credential-bearing URLs are excluded.
- The collector never signs in, pays, bypasses DRM, or bypasses geo-restrictions.
- The current seed set is limited to Bangladesh Television's public live pages. Other regions/categories remain empty until an official, public, free-to-air source is verified.

## Validation
- Private/local-network destinations and non-global IPs are rejected.
- HTTP success alone is not enough: HLS manifest and first media segment are checked.
- GitHub Actions runs outside Bangladesh, so speed tests cannot guarantee playback on a Bangladesh ISP.

## Outputs
- `source_intelligence/output/combined.m3u`: fastest primary links from approved sources
- `source_intelligence/output/all_fast_sources.m3u`: all fast approved links
- `source_intelligence/output/backup_slow.m3u`: slower reachable approved links
- Category playlists, `channel_report.csv`, source and link diagnostics
- `source_intelligence/data/registry.sqlite3`: source, channel, and link history
