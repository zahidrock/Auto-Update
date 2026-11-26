# IPTV Source Intelligence

This is a separate collection engine alongside the existing updater. It does not overwrite `auto_update.py`, `playlist.m3u`, or the existing workflow.

## First-stage behavior

- Reads configured public playlist/index seeds.
- Parses M3U/M3U8 entries and recursively follows playlist-like URLs found inside those sources.
- Stores discovered channels, source URLs, and validation results in SQLite.
- Checks HTTP access and HLS playlist/segment reachability.
- Produces a fast-only combined playlist, category playlists, an all-fast playlist, and a slower/uncertain archive.
- Runs daily in GitHub Actions; no local PC is required.

## Important limits

A GitHub Actions runner is not located in Bangladesh. Its measured throughput is only a rough filter and cannot guarantee playback speed on a Bangladeshi ISP. DRM, login, geo-blocking, token expiry, and provider-side restrictions can also affect playback.

Only collect streams that are publicly offered for use or that you are authorized to access. Do not use leaked private API keys, stolen credentials, or bypass access controls. Put any personally authorized API keys in GitHub Actions Secrets, never in repository files.

## Files

- `config/settings.json`: thresholds, concurrency, and output settings.
- `config/seeds.txt`: starting public playlist URLs. Add more trusted public sources here.
- `src/main.py`: discovery, validation, database, and playlist generation.
- `.github/workflows/source-intelligence.yml`: daily automation.

The existing updater remains independent.
