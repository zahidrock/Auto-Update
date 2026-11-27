# IPTV Source Intelligence

Automated discovery and validation of publicly offered, authorized free-to-air streams.

## Automation
- Runs daily in GitHub Actions.
- Runs automatically after source/config/code changes on `main`.
- Manual run: **Actions → IPTV Source Intelligence → Run workflow**.
- No local PC is required.

## Strict source approval
The collector uses the explicit `approved_source_hosts` and `approved_stream_hosts` lists in `source_intelligence/config/settings.json`. At present, only the official BTV domains are approved. Third-party playlist aggregators and unverified indexes are excluded.

A new host may be added only after its stream is linked from an official broadcaster/government page and is publicly offered without a subscription, account login, DRM circumvention, or geo-restriction bypass. If the broadcaster uses a CDN, approve that CDN hostname only after verifying the official page links to it. Signed or credential-bearing URLs are rejected.

Before each run, old database rows outside the allowlists are removed. Playlist and report generation applies the allowlist again, so stale unapproved links cannot reappear in published outputs. Some category playlists may remain empty until more official sources are verified.

## Outputs
- `source_intelligence/output/combined.m3u`: best fast primary link per channel
- `source_intelligence/output/all_fast_sources.m3u`: all fast links
- `source_intelligence/output/backup_slow.m3u`: slower approved links
- Category playlists and `channel_report.csv`
- `source_intelligence/data/registry.sqlite3`: approved source, channel, and link history

## Validation limits
The workflow checks HTTP response, initial throughput, and HLS media-segment reachability. Checks run from GitHub's cloud runner, not from Bangladesh; measured speed cannot guarantee playback on a local ISP.
