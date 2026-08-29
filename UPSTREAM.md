# Upstream

This repository started from the official [EvenDemoApp](https://github.com/even-realities/EvenDemoApp)
project for Even Realities G1.

- Imported: 2026-08-30
- Upstream `main`: `3899aac2b39ce969582cf6eb96ecb36be3e0e9e6`
- Upstream `develop`: `efdfcaa1e9c0e11eb7eddb675749d80503d3f3a3`
- Upstream license: BSD-2-Clause

The private history is a sanitized import: hard-coded API credential values
present in the upstream source were removed and replaced with a required
`--dart-define=DASHSCOPE_API_KEY=...` value. The public upstream repository was
not modified. The local `upstream` remote is fetch-only; development changes
belong on `origin` (`TrillionniumFoundation/hepta-glasses`).
