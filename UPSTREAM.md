# Upstream

This repository started from the official [EvenDemoApp](https://github.com/even-realities/EvenDemoApp)
project for Even Realities G1.

- Imported: 2026-08-30
- Upstream `main`: `3899aac2b39ce969582cf6eb96ecb36be3e0e9e6`
- Observed upstream root tree: `bc593f9b23ce9a49ead8b5652181639157032572`
- Upstream commit time observed through the GitHub Git Data API: `2026-06-09T08:27:17Z`
- Upstream commit signature state observed through the GitHub Git Data API: unsigned/unverified
- Upstream `develop`: `efdfcaa1e9c0e11eb7eddb675749d80503d3f3a3`
- Upstream license: BSD-2-Clause

The upstream commit/root-tree pair is an external observation. Those two root
objects are not present in this repository object database and require live
independent revalidation. Imported native subtrees and blobs that are present
locally are bound separately in `third_party/native-import-provenance.json` and
validated by `tools/native/validate_provenance.py`.

The private history is a sanitized import: hard-coded API credential values
present in the upstream source were removed and replaced with a required
`--dart-define=DASHSCOPE_API_KEY=...` value. The public upstream repository was
not modified. The local `upstream` remote is fetch-only; development changes
belong on `origin` (`TrillionniumFoundation/hepta-glasses`).
