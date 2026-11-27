# IPTV Source Intelligence

## Current source policy

- Only hosts listed in `config/settings.json` under `approved_source_hosts` and `approved_stream_hosts` are fetched or published.
- The current allowlist is limited to the official BTV live portal and BTV website domains.
- The seed list contains only official BTV live pages. Unverified public playlist aggregators are not treated as proof of broadcast authorization.
- HLS redirects and media-segment hosts must also remain on the approved host list.
- Explicit geo-blocked, subscription, pay-TV, login, and DRM-marked entries are rejected.
- Signed/credential-bearing URLs, private IPs, and local hosts are rejected.

To add a broadcaster, first verify that its official website links to the stream and makes it publicly available without login, subscription, DRM circumvention, or geo-restriction bypass. If it uses a CDN, add that exact CDN hostname only after verifying the official link. Do not add third-party playlist collections merely because they are publicly downloadable.

The collector prunes old database rows outside the current allowlists before discovery and filters again when generating playlists. Empty category playlists are expected until more official free-to-air sources are verified.

## Files

- `config/settings.json`: host allowlists, thresholds, and output settings.
- `config/seeds.txt`: official broadcaster pages to inspect.
- `src/main.py`: discovery, validation, database, and playlist generation.
- `.github/workflows/source-intelligence.yml`: GitHub Actions automation.

A GitHub Actions runner is not located in Bangladesh. Its speed measurements are only a rough filter and cannot guarantee local playback.
