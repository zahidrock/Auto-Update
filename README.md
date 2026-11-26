# IPTV Source Intelligence

Automated discovery and validation of publicly available IPTV playlist sources.

## Run
Open **Actions → IPTV Source Intelligence → Run workflow**.

The workflow also runs daily at 02:35 Bangladesh time.

## Outputs
- `source_intelligence/output/combined.m3u` — best fast link per channel
- `source_intelligence/output/all_fast_sources.m3u` — all validated fast links
- `source_intelligence/output/backup_slow.m3u` — slower links kept separately
- Category playlists and `channel_report.csv`
- `source_intelligence/data/registry.sqlite3` — source/channel/link history

## Configuration
- Add public playlist/index URLs to `source_intelligence/config/seeds.txt`.
- Adjust thresholds in `source_intelligence/config/settings.json`.

Only use streams and APIs that are publicly offered for use or that you are authorized to access. Do not commit private keys or credential-bearing URLs.

Speed checks run from GitHub's runner and cannot guarantee playback performance on every ISP or location.
