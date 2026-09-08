# Mobile product identity

Status: canonical user-visible mobile identity and explicit compatibility boundary.

## Canonical release-facing identity

The product name presented to users is **Hepta Glasses**.

Android installs use application ID `org.trillionnium.heptaglasses` and the launcher label `Hepta Glasses`. The application ID is an upgrade, signing, store and account identity; changing it requires an explicit migration and release-authority review.

iOS presents `Hepta Glasses` as `CFBundleDisplayName` and uses `hepta_glasses` as the non-localized bundle name. `CFBundleIdentifier` remains sourced from `PRODUCT_BUNDLE_IDENTIFIER`; the final identifier, provisioning profile, entitlement application identifier and signing certificate must agree before a distributable binary can qualify.

Permission copy names the product, describes the immediate capability and avoids implying that Bluetooth, photo access or speech recognition runs continuously.

## Compatibility namespaces

The inherited Dart package and Kotlin/Swift source namespaces are implementation compatibility identifiers, not installed-product authority. They may retain legacy `demo_ai_even` or `com.example.demo_ai_even` names until an atomic migration updates every import, package declaration, generated binding, test path and native registration in one reviewed change.

A partial internal rename is prohibited because it can silently break Flutter imports, Android manifest resolution, generated `R`/`BuildConfig` references, MethodChannel registration or native tests. The migration must preserve application data/upgrade behavior and be independently qualified on both platforms.

## Validation

`services/qualification/test_mobile_product_identity.py` verifies the current release-facing names, the Android application ID, the Android launcher label, the iOS display and bundle names, and the absence of the old demo title from mobile release surfaces.

This test does not close signing, provisioning, store registration, physical-device qualification or the future internal namespace migration. Those require their own exact candidate and authority evidence.
