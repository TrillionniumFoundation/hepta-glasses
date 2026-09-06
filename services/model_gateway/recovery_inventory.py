"""Stable pagination over durable unresolved model request metadata.

This module performs no provider I/O and never consumes a readback claim. It is
an operator inventory helper for ``ProductionModelGateway`` on the same trusted
host, not authenticated ingress or a remote recovery service.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from services.model_gateway.production import (
    ModelReceipt,
    ProductionModelGateway,
    fail,
    identifier,
)


@dataclass(frozen=True)
class ModelRecoveryPage:
    """One subject-scoped keyset page and its optional continuation cursor."""

    records: tuple[ModelReceipt, ...]
    next_after: str | None


def _cursor(value: object) -> str:
    if type(value) is not str or (value and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value)):
        fail("model_inventory_cursor_invalid")
    return value


def recoverable_page(gateway: ProductionModelGateway, *, subject: str,
                     after: str = "", limit: int = 100) -> ModelRecoveryPage:
    """Return one consistent page of prepared/indeterminate request metadata.

    ``after`` is the last ``idempotency_key`` returned by the preceding page.
    The query fetches one extra row so ``next_after`` is emitted only when more
    matching rows existed in this transaction. Concurrent inserts at or before
    an already-consumed cursor require a later rescan from the empty cursor.
    """
    if not isinstance(gateway, ProductionModelGateway):
        fail("model_inventory_gateway_invalid")
    identifier(subject)
    after = _cursor(after)
    if type(limit) is not int or not 1 <= limit <= 100:
        fail("model_inventory_limit_invalid")

    # BEGIN IMMEDIATE gives one page a coherent local snapshot and serializes it
    # with admission. It does not freeze the complete multi-page scan.
    with gateway.storage.transaction() as db:
        rows = db.execute(
            "SELECT * FROM requests WHERE subject=? "
            "AND state IN ('prepared','indeterminate') "
            "AND idempotency_key>? ORDER BY idempotency_key LIMIT ?",
            (subject, after, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        records = tuple(gateway._receipt(db, row) for row in rows[:limit])
        return ModelRecoveryPage(
            records,
            records[-1].idempotency_key if has_more else None,
        )
