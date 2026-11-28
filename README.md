# Public IPTV Source Intelligence

Automated discovery and validation of publicly accessible IPTV playlists and streams.

## Automation
- Runs daily in GitHub Actions.
- Runs after source/config/code changes on `main`.
- Manual run: **Actions → IPTV Source Intelligence → Run workflow**.
- No local PC is required.

## Public source discovery
- Public community playlist indexes, including iptv-org and Free-TV.
- Automatic GitHub repository search for public M3U/M3U8 playlist files.
- Recursive discovery of nested playlists.
- Stream URLs may use any globally reachable public host; they are not limited to broadcaster-owned domains.

## Safety and validation
- Private/local-network destinations, credential-bearing URLs, and signed/expiring links are rejected.
- Obvious subscription, login, geo-block, pay-TV, and DRM-labelled entries are excluded.
- A public URL is not proof of copyright permission. The collector only tests freely accessible streams and never bypasses payment, login, DRM, or geo-restrictions.
- HTTP success alone is not enough: HLS manifest and first media segment are checked.
- GitHub Actions runs outside Bangladesh, so speed tests cannot guarantee playback on a Bangladesh ISP.

## Outputs
- `source_intelligence/output/combined.m3u`: fastest primary links
- `source_intelligence/output/all_fast_sources.m3u`: all fast links
- `source_intelligence/output/backup_slow.m3u`: slower reachable links
- Category playlists, `channel_report.csv`, source and link diagnostics
- `source_intelligence/data/registry.sqlite3`: source, channel, and link history
