# Dependabot configuration object custody

Status: closed-world repository-source control for `.github/dependabot.yml`.

## Exact reviewed object

The complete 749-byte configuration object, including final LF, is bound by SHA-256:

```text
c50632e8373a28bceeb5fcd6716172a3cecf97e46f31ad85a49787c638f227a5
```

`tools/native/dependabot_config_custody.py --check` rejects any byte movement before returning the reviewed ecosystem, directory, schedule, timezone, proposal-limit, registry and promotion properties. The canonical services suite invokes the tool through `services/qualification/test_dependabot_config_custody.py`; no second workflow authority is introduced.

This complete-object boundary complements the externally pinned official ecosystem-value check. The official check proves that the three reviewed unquoted values are supported by the pinned `github/docs` object. The complete-object boundary proves that the real YAML file has not acquired additional entries or authority-bearing syntax that a narrow value extractor could miss.

## Closed syntax surface

The accepted file contains only these ordered entries:

| Ecosystem | Directory | Monday time | Limit |
| --- | --- | --- | ---: |
| `github-actions` | `/` | `03:00` | 5 |
| `pub` | `/` | `03:15` | 5 |
| `gradle` | `/android` | `03:30` | 5 |

All schedules use `Asia/Singapore`. There is no auto-merge, target-branch override, external registry, insecure external-code execution, CocoaPods entry or Swift Package Manager substitution.

Valid YAML has multiple equivalent spellings. Quoted YAML scalars, anchors, aliases, and merge keys can therefore evade a parser that recognizes only one textual form. The complete-object SHA-256 rejects those alternate forms, extra maps, duplicate surfaces, comments used to retain misleading tokens, and schedule or authority drift unless the custody constant and its hostile tests move in the same reviewed change.

## Change procedure

No configuration movement inherits this object’s CI, Artifact or review credit. A legitimate change must:

1. update `.github/dependabot.yml`;
2. update the reviewed digest and exact expected shape;
3. add or change hostile fixtures for the new syntax and authority surface;
4. run all seven canonical jobs on the unchanged new head;
5. download and independently verify the exact-head Artifact;
6. obtain an eligible non-pusher review with all conversations resolved;
7. adopt only through the ordinary stacked and protected path.

This boundary does not declare a dependency update safe, auto-approve a proposal, configure repository branch protection, or supply provider, device, signing, store or release authority.
