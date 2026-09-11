# Mobile product identity

"
    "Status: canonical release-facing and internal source identity.

"
    "## Canonical identity

"
    "The product name is **Hepta Glasses**. The Dart package is `hepta_glasses`. "
    "Android source packages, Gradle namespace and installed application ID are "
    "`org.trillionnium.heptaglasses`. JNI registrations use the same package path. "
    "iOS presents `Hepta Glasses`, uses `hepta_glasses` as its bundle name and binds "
    "all Runner application configurations to `org.trillionnium.heptaglasses`; test "
    "bundles use the corresponding `.RunnerTests` suffix.

"
    "## Atomic migration invariants

"
    "The migration moves every Android main, unit-test and available instrumentation "
    "package tree together; rewrites all Dart package imports, Kotlin declarations, "
    "repository path references, JNI symbols and source-bound protocol references; "
    "and recomputes the canonical G1 matrix digest after those path changes. A partial "
    "rename is forbidden because it can split generated resources, MethodChannel "
    "registration, native bindings, tests or evidence ownership.

"
    "Application data continuity is anchored by the unchanged Android application ID "
    "and iOS bundle identifier. The source rename therefore does not authorize a new "
    "store identity or a data-container migration.

"
    "## Validation

"
    "`services/qualification/test_mobile_product_identity.py` checks package identity, "
    "directory layout, Kotlin declarations, JNI symbols, Apple build settings and the "
    "absence of inherited demo identifiers across active source, contract, test and "
    "documentation surfaces. Canonical Flutter, Android, iOS and native CI must pass on "
    "the unchanged final head.

"
    "## Authority boundary

"
    "This source migration does not close production signing, provisioning, credential, "
    "store-registration, physical-device, vendor-firmware, pilot, rollout or release "
    "authority. Those remain external evidence gates.
"
