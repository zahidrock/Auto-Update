# IPTV Source Intelligence

Automated discovery and validation of publicly available IPTV playlists.

## Automation
- Runs daily at 02:35 Bangladesh time.
- Runs automatically after source/config/code changes on `main`.
- Manual run: **Actions → IPTV Source Intelligence → Run workflow**.
- No local PC is required.

## Discovery sources
The seed list includes iptv-org country, language and category playlists, plus curated public collections and public index documents. The crawler follows explicit playlist URLs found in those documents, subject to source/depth limits.

Add more trusted public playlist or index URLs to `source_intelligence/config/seeds.txt`.

## Outputs
- `source_intelligence/output/combined.m3u`: best fast primary link per channel
- `source_intelligence/output/all_fast_sources.m3u`: all fast links
- `source_intelligence/output/backup_slow.m3u`: slower links kept separately
- Category playlists and `channel_report.csv`
- `source_intelligence/data/registry.sqlite3`: source, channel, and link history

## Validation
The workflow checks HTTP response, initial data throughput, and HLS media-segment reachability. Checks run from GitHub's cloud runner, not from Bangladesh; measured speed is only a filter and cannot guarantee playback on a local ISP. Geo-blocking, DRM, account requirements, expiring links, and provider policies can still prevent playback.

## Safety and usage
Only use streams/APIs that are publicly offered for use or that you are authorized to access. Do not commit private keys, leaked credentials, signed URLs, or subscription URLs. The crawler rejects common credential-bearing URL patterns and local/private IP literals, uses bounded concurrency, and retries temporary rate limits with backoff.
