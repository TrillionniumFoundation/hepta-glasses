# G5 final exact-head source candidate v4

This administrator-authored commit follows the fail-closed all-history scan
scope repair. The scan includes binary blob content and rejects any blob above
the auditable size limit rather than silently omitting it. Source closure still
requires ordinary CI and downloaded-artifact round-trip verification bound to
this exact commit and tree.

This remains E0-E4 source evidence only. All physical, production,
administrative, vendor, independent-assurance, signing, pilot, rollout,
rollback, and store gates remain separately evidenced.

Canonical plan revision: `2026-08-31-g5`.
