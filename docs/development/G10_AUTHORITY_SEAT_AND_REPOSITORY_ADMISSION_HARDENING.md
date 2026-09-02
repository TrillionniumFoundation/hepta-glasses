# G10 authority-seat and repository-admission hardening

## Scope

This note strengthens `HG-0076` and `HG-0079` after adversarial review of the
first G10 candidate. It does not add product authority and does not change the
inherited twelve E5–E7, administrative, upstream, or independent gates.

## Cross-gap authority-seat consistency

The base quorum policy already requires distinct key IDs and distinct
identity/organization pairs for multiple authority seats inside one gap. A
second rule is required across the complete package: a broadly enrolled key
must not act as unrelated authority classes merely because those classes occur
in different gaps.

`authority_seat_policy.py` therefore installs these invariants over the final
validated submission set:

1. one issuer key ID maps to exactly one authority class throughout one
   complete package;
2. one issuer identity/organization pair maps to exactly one authority class
   throughout one complete package;
3. a key or identity pair may appear in multiple gaps only when the authority
   class is unchanged; and
4. the original per-gap rule still prevents one key or identity pair from
   filling two seats in the same gap.

This permits a narrowly scoped `physical_device_lab` key to attest both
`HG-0010` and the physical portion of `HG-0018`, while preventing that key from
also acting as a credential provider, cloud-security owner, repository
administrator, store authority, or another unrelated role.

Hostile tests construct otherwise valid, fully signed, complete bundles whose
trust registry deliberately authorizes one key or identity pair for unrelated
classes. Validation must reject those packages after cryptographic primitive
checks but before complete closure can become true.

## Descriptor-anchored repository admission

The initial recursive admission check protected the final file component with
`O_NOFOLLOW` and compared lexical/opened file identities. That is insufficient
when a parent directory is replaced between enumeration and open: a final-file
no-follow flag does not stop the kernel from traversing a symbolic or ordinary
replacement in an ancestor component.

`repository_admission.py` makes repository discovery a fail-closed directory
transaction:

- the evidence root is opened from the filesystem anchor with no-follow
  directory traversal;
- every child directory is inspected without following links, opened relative
  to its already-open parent, and required to preserve the same
  device/inode/mode/size/mtime/ctime identity before, during, and after
  recursion;
- every file is inspected, opened, read, and re-observed relative to the same
  parent descriptor, with lexical/opened/post-read identity equality;
- symbolic links and special objects anywhere below `evidence/external` fail
  the gate instead of being silently ignored;
- file size, aggregate byte count, entry count, and recursion depth are bounded;
- duplicate-member, non-finite, malformed, and non-object JSON cannot be
  promoted into a canonical accepted envelope; and
- accepted envelopes are identified by canonical content, not filename,
  extension, or nesting depth.

A separate repository qualification test invokes this scanner over the actual
committed evidence root. Every discovered accepted package is then passed to
the normal complete G10 validator with the protected out-of-band registry pin.
The legacy discovery tests remain useful compatibility coverage, but the new
scanner is the fail-closed admission authority.

## Trusted-process boundary

G10 trusts the verifier Python process and source object. The deterministic
fixed-clock helper is a test-only, underscored in-process surface; it is not a
sandbox against code already capable of importing arbitrary source modules or
monkey-patching Python objects. Such code has equivalent process compromise
and is outside the declared validator threat model. All supported operational
entrypoints—the package API, direct policy module, compatibility import under
its package name, and executable CLI—continue to reject a caller-supplied time
or cryptographic executable before reading evidence.

This distinction must remain explicit: absence from `__all__` is API hygiene,
not an isolation mechanism. Release validation must run in a controlled process
that does not execute untrusted Python code.

## Required regression evidence

The complete source gate must include:

- cross-gap different-class key alias rejection;
- cross-gap different-class identity/organization alias rejection;
- allowed same-class reuse across related gaps;
- opaque nested accepted-envelope discovery;
- symbolic-link entry rejection;
- regular-file replacement rejection between stat and open;
- ordinary-directory replacement rejection between stat and open;
- complete repository revalidation under an external pin when an accepted
  package is present; and
- all pre-existing G8, G9, and G10 tests, mobile builds, sanitizers, history
  scan, and content-addressed exact-head evidence.

## Reopen conditions

Reopen `HG-0076` if one key or identity/organization pair can represent two
unrelated authority classes anywhere in one complete package.

Reopen `HG-0079` if accepted-package discovery follows a symbolic link, ignores
an unsafe special object, traverses a replaced directory, accepts a replaced
file, exceeds its resource bounds, relies on a filename convention, or fails to
revalidate every discovered accepted envelope under the external trust pin.
