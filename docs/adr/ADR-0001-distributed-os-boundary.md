
# ADR-0001: distributed glasses OS boundary

Status: Accepted — 2026-08-30

The current repository is a companion application, not G1 firmware. The product is therefore
implemented as a distributed OS: firmware-defined glasses device plane, phone edge runtime, cloud
control plane, and isolated specialist workers. This preserves the existing device integration
without claiming vendor firmware authority that the repository does not have.

Consequences: device effects remain on the phone edge authority; the glasses store no provider
master key; physical firmware work is a separate upstream-dependent package.
