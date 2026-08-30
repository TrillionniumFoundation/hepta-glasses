# Third-party source inventory

`components.json` is the canonical, machine-readable inventory for source vendored directly into this repository. It is consumed by `services/qualification/sbom.py` and validated by `tools/validate_repository.py`.

Each component declares:

- a stable component name and declared upstream project;
- supplier and SPDX license expression;
- one or more repository paths owned by the component;
- optional excluded paths when a nested file belongs to another component;
- a content digest computed from the exact files in the checked source tree.

The manifest intentionally does not guess an upstream release or commit that cannot be proven from the imported tree. A maintainer adding or replacing vendored source must record the exact upstream revision, preserve all notices, document local patches, update path ownership, regenerate the SBOM, and obtain an independent license/security review before product release.

A declared license and content digest are source evidence. They are not proof of vendor authorization, patent clearance, binary composition, or independent legal approval.
