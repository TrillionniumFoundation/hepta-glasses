# Exact-domain HTTPS egress broker

`https_egress.py` is a trusted-host network primitive for a separately isolated
Skill or specialist worker. It is not itself a network sandbox.

## Contract

Trusted composition constructs an immutable `EgressPolicy` with an exact sorted
set of lowercase DNS names. Wildcards, IP literals, userinfo, non-HTTPS schemes,
ports other than 443, fragments, Unicode request targets, CR/LF escapes and
noncanonical percent escapes are rejected. Calls are restricted to GET without a
body or POST with bounded opaque bytes; package-controlled headers are not
accepted.

DNS runs in a bounded isolated Python helper. Every returned IPv4/IPv6 address
must be globally routable; a mixed public/private answer fails the whole request.
The broker connects to one of those numeric addresses under one shared deadline,
then uses the original allowlisted hostname for TLS SNI and certificate hostname
verification. It never consults proxy environment variables or re-resolves the
name during connection.

The broker emits exactly one HTTP/1.1 request after TLS. It requests identity
encoding and never follows redirects. Redirect status or `Location`, protocol
upgrade, transfer encoding, compression, duplicate critical headers, malformed
content length, excessive header/body size, truncation and deadline exhaustion
all fail closed. It returns immutable response headers and bounded raw bytes.

## Security and availability boundary

This module does not prevent arbitrary child code from opening its own socket.
Broker-exclusive egress requires an OS sandbox/network namespace/seccomp policy
that denies child networking and exposes only a capability-mediated IPC channel
to this broker. It also does not provide request quotas, OAuth credential
selection, tenant authorization, HTTP/2, retries, remote idempotency, provider
receipts or independent external evidence. DNSSEC is not required; pinning the
resolved numeric address through TLS prevents post-resolution redirection, while
a malicious resolver can still cause denial of service.

Resolver, TCP, TLS, send and response parsing share one caller deadline. TCP
connect may try multiple already-approved addresses before any HTTP bytes are
sent; the application request is never retried. Production observability must log
only stable error codes and safe aggregate metadata, not URLs containing personal
query data, bodies, credentials, certificate contents or raw server responses.

Run `python3 -m unittest services.codex_worker.test_https_egress -v`. Tests use
local socket pairs and injected numeric addresses to exercise actual CPython
HTTP parsing without internet traffic. They do not qualify public DNS, TLS roots,
provider tenancy or a deployed isolation boundary.
