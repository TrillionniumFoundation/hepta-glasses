# Active module engineering handoff

`docs/modules/modules.json` is the single active module registry. `docs/MODULE_COVERAGE.json` is a compatibility pointer, while G8/G9/G10 and date-stamped registries are retained as historical lineage only.

Every generated module page binds its complete canonical record with a SHA-256 digest and enumerates source roots, contracts, documentation, tests, platform status, evidence ceiling, and external gates. The generated pages improve reviewability; they do not replace owner-authored design documents or external evidence.

| Module | Owner | Lifecycle | Primary engineering document |
|---|---|---|---|
| [`mobile-shell`](./mobile-shell/README.md) | `mobile` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#mobile-shell` |
| [`edge-runtime`](./edge-runtime/README.md) | `runtime` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#edge-runtime` |
| [`policy-tool-gateway`](./policy-tool-gateway/README.md) | `runtime-security` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#policy-tool-gateway` |
| [`audit-journal`](./audit-journal/README.md) | `runtime-security` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#audit-journal` |
| [`g1-transport`](./g1-transport/README.md) | `device` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#g1-transport` |
| [`g1-protocol-features`](./g1-protocol-features/README.md) | `device-runtime` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#g1-protocol-features` |
| [`assistant-speech`](./assistant-speech/README.md) | `mobile-ai` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#assistant-speech` |
| [`android-native`](./android-native/README.md) | `android` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#android-native` |
| [`ios-native`](./ios-native/README.md) | `ios` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#ios-native` |
| [`digital-twin`](./digital-twin/README.md) | `device` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#digital-twin` |
| [`model-gateway-service`](./model-gateway-service/README.md) | `ai-platform` | `development_reference` | `docs/development/DURABLE_MODEL_GATEWAY.md` |
| [`identity-control-plane`](./identity-control-plane/README.md) | `cloud-security` | `development_reference` | `docs/development/DURABLE_IDENTITY.md` |
| [`realtime-control-plane`](./realtime-control-plane/README.md) | `cloud` | `development_reference` | `docs/development/REALTIME_ADMISSION.md` |
| [`capability-control-plane`](./capability-control-plane/README.md) | `capabilities` | `development_reference` | `docs/development/DURABLE_CAPABILITIES.md` |
| [`skills-registry`](./skills-registry/README.md) | `skills` | `development_reference` | `docs/development/SIGNED_SKILLS.md` |
| [`memory`](./memory/README.md) | `privacy` | `development_reference` | `docs/development/DURABLE_MEMORY.md` |
| [`codex-worker`](./codex-worker/README.md) | `developer-platform` | `development_reference` | `services/codex_worker/README.md` |
| [`mcp-adapter`](./mcp-adapter/README.md) | `developer-platform` | `development_reference` | `docs/MODULE_DEVELOPMENT_GUIDE.md#mcp-adapter` |
| [`qualification-release`](./qualification-release/README.md) | `release` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#qualification-release` |
| [`contracts-compatibility`](./contracts-compatibility/README.md) | `architecture` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#contracts-compatibility` |
| [`repository-governance`](./repository-governance/README.md) | `repository-admin` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#repository-governance` |
| [`native-dependencies`](./native-dependencies/README.md) | `native-tooling` | `source_candidate` | `docs/MODULE_DEVELOPMENT_GUIDE.md#native-dependencies` |
| [`external-evidence-authentication`](./external-evidence-authentication/README.md) | `release-security` | `source_candidate` | `docs/development/G9_TERMINAL_EXTERNAL_CLOSURE.md` |
| [`latest-head-ci-custody`](./latest-head-ci-custody/README.md) | `quality-gates` | `source_candidate` | `docs/adr/ADR-0005-latest-head-ci-concurrency.md` |
| [`authority-quorum-review-integrity`](./authority-quorum-review-integrity/README.md) | `release-security` | `source_candidate` | `docs/development/G10_AUTHORITY_QUORUM_AND_REVIEW_INTEGRITY.md` |
| [`agent-os-plugin`](./agent-os-plugin/README.md) | `developer-platform` | `development_reference` | `plugins/hepta-glasses-agent-os/DEVELOPMENT.md` |

## Verification

```bash
python3 tools/generate_module_docs.py --check
python3 tools/validate_module_semantics.py
```
