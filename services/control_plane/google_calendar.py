"""Narrow Calendar event creation/readback over authenticated HTTPS.

Host-only adapter: use DurableCapabilityGateway, verified single-use leases and
an external OAuth vault. No consent UI, refresh token storage, guest invitations,
background retries, compensation, or independent provider attestation is added.
"""
from __future__ import annotations

import http.client
import json
import re
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote

from .capabilities import CapabilityError, CapabilityRequest, CapabilitySpec, RiskTier, canonical_digest
from .durable_capabilities import ProviderObservation
from .durable_state import deadline, identifier, timestamp

PROFILE = "google-calendar-owned-single-event-v1"
SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
MAX_RESPONSE_BYTES = 65536
SPEC = CapabilitySpec("calendar.event.create", RiskTier.R2, True,
                      frozenset({"title", "start_at", "end_at"}),
                      reconciliation_supported=True)


def fail(code: str) -> None:
    raise CapabilityError(code)


def _name(value: object) -> str:
    if type(value) is not str or not identifier(value, 256):
        fail("calendar_binding_invalid")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise CapabilityError("calendar_binding_invalid") from None
    return value


def _json(raw: bytes) -> dict:
    def unique(pairs):
        value = {}
        for key, child in pairs:
            if key in value:
                fail("calendar_response_json_invalid")
            value[key] = child
        return value
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: fail("calendar_response_json_invalid"))
        if type(value) is not dict:
            fail("calendar_response_json_invalid")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise CapabilityError("calendar_response_json_invalid") from None


def _utc(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _instant(value: object) -> datetime:
    # Provider may normalize to another offset. Compare actual instants, never
    # accept all-day values, naive datetimes, fractional drift or an unknown -00:00.
    if (type(value) is not str or len(value) > 40 or value.endswith("-00:00")
            or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value)):
        fail("calendar_event_time_invalid")
    if not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        fail("calendar_event_time_invalid")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise CapabilityError("calendar_event_time_invalid") from None


@dataclass(frozen=True, repr=False)
class CalendarAccessGrant:
    """External vault's exact-operation grant; never construct from client JSON.

    The vault must authenticate the actual Google account, scope and calendar
    ownership. These Python fields do not cryptographically verify an OAuth token.
    Token bytes must never be logged, serialized to disk or placed in test fixtures.
    """
    subject: str
    account_id: str
    calendar_id: str
    operation_id: str
    request_digest: str
    purpose: str  # execute or readback
    scopes: frozenset[str]
    expires_at: int
    access_token: str


@dataclass(frozen=True)
class GoogleCalendarAdapter:
    subject: str = field(repr=False)
    account_id: str = field(repr=False)
    calendar_id: str = field(repr=False)
    grant: Callable[[str, str, str], CalendarAccessGrant] = field(repr=False, compare=False)
    clock: Callable[[], int] = field(repr=False, compare=False)
    timeout_seconds: float = 5

    def __post_init__(self) -> None:
        for value in (self.subject, self.account_id):
            _name(value)
        if (type(self.calendar_id) is not str or self.calendar_id.lower() == "primary"
                or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,256}", self.calendar_id)
                or not callable(self.grant) or not callable(self.clock)
                or not deadline(self.timeout_seconds)):
            fail("calendar_configuration_invalid")

    @property
    def provider_id(self) -> str:
        return canonical_digest({"profile": PROFILE, "subject": self.subject,
                                 "account": self.account_id, "calendar": self.calendar_id,
                                 "scope": SCOPE})

    @property
    def capability_spec(self) -> CapabilitySpec:
        return SPEC

    def _now(self) -> int:
        now = self.clock()
        if not timestamp(now):
            fail("calendar_clock_invalid")
        return now

    def _request(self, request: CapabilityRequest, operation_id: str):
        if (type(request) is not CapabilityRequest or request.subject != self.subject
                or request.name != SPEC.name or not timestamp(request.deadline)
                or type(operation_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", operation_id)
                or type(request.arguments) is not dict or set(request.arguments) != SPEC.required_fields):
            fail("calendar_request_binding_invalid")
        for value in (request.request_id, request.task_id, request.device_id, request.idempotency_key):
            _name(value)
        args = dict(request.arguments)
        title, start, end = args["title"], args["start_at"], args["end_at"]
        if (type(title) is not str or not title.strip() or len(title) > 256
                or any(ord(c) < 32 or ord(c) == 127 for c in title)
                or not timestamp(start) or not timestamp(end) or not 0 < end - start <= 86400):
            fail("calendar_event_arguments_invalid")
        try:
            if len(title.encode("utf-8")) > 1024:
                fail("calendar_event_arguments_invalid")
            start_time, end_time = _utc(start), _utc(end)
        except (ValueError, OverflowError, OSError, UnicodeError):
            raise CapabilityError("calendar_event_arguments_invalid") from None
        argument_digest = canonical_digest(args)
        binding = canonical_digest({"request": request.fingerprint,
                                    "deadline": request.deadline, "provider": self.provider_id,
                                    "operation": operation_id})
        event_id = "h" + canonical_digest({"profile": PROFILE, "provider": self.provider_id,
                                          "operation": operation_id})
        body = {"id": event_id, "summary": title, "start": {"dateTime": start_time},
                "end": {"dateTime": end_time}, "eventType": "default", "status": "confirmed",
                "visibility": "private", "transparency": "opaque",
                "reminders": {"useDefault": False}, "attendees": [],
                "guestsCanInviteOthers": False, "guestsCanModify": False,
                "extendedProperties": {"private": {"hgOperation": operation_id,
                    "hgProvider": self.provider_id, "hgArguments": argument_digest}}}
        return body, argument_digest, binding

    def execute(self, request: CapabilityRequest, operation_id: str) -> ProviderObservation:
        # Prevent accidental use through an older gateway that cannot revalidate
        # the consumed lease after a slow OAuth vault/TLS operation.
        fail("calendar_revalidating_gateway_required")

    def execute_authorized(self, request: CapabilityRequest, operation_id: str, *,
                           authorize: Callable[[], None]) -> ProviderObservation:
        if not callable(authorize):
            fail("calendar_revalidating_gateway_required")
        body, argument_digest, binding = self._request(request, operation_id)
        authorize()
        value = self._exchange("POST", request, operation_id, body, binding, authorize)
        return self._observation(value, body, operation_id, argument_digest)

    def readback(self, request: CapabilityRequest, operation_id: str,
                 external_id: str | None) -> ProviderObservation:
        body, argument_digest, binding = self._request(request, operation_id)
        if external_id is not None and external_id != body["id"]:
            fail("calendar_external_id_mismatch")
        # Old mutation authority may be expired/revoked. The host must obtain
        # separate currently authorized readback access through its OAuth vault.
        value = self._exchange("GET", request, operation_id, body, binding, None)
        return self._observation(value, body, operation_id, argument_digest)

    def _check_grant(self, grant: CalendarAccessGrant, operation: str, binding: str, purpose: str) -> None:
        if (type(grant) is not CalendarAccessGrant
                or (grant.subject, grant.account_id, grant.calendar_id, grant.operation_id,
                    grant.request_digest, grant.purpose) !=
                   (self.subject, self.account_id, self.calendar_id, operation, binding, purpose)
                or type(grant.scopes) is not frozenset or grant.scopes != frozenset({SCOPE})
                or not timestamp(grant.expires_at) or grant.expires_at <= self._now()
                or type(grant.access_token) is not str or not 20 <= len(grant.access_token) <= 4096
                or any(not 33 <= ord(c) <= 126 for c in grant.access_token)):
            fail("calendar_oauth_grant_invalid")

    def _exchange(self, method, request, operation, body, binding, authorize):
        stop = time.monotonic() + self.timeout_seconds
        purpose = "execute" if method == "POST" else "readback"
        connection = response = access = None
        def remaining():
            wait = stop - time.monotonic()
            if wait <= 0:
                fail("calendar_transport_deadline")
            return wait
        try:
            access = self.grant(operation, binding, purpose)
            self._check_grant(access, operation, binding, purpose)
            path = "/calendar/v3/calendars/" + quote(self.calendar_id, safe="") + "/events"
            if method == "POST":
                path += "?sendUpdates=none&supportsAttachments=false&conferenceDataVersion=0"
                payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            else:
                path += "/" + body["id"]
                payload = None
            connection = http.client.HTTPSConnection("www.googleapis.com", 443,
                context=ssl.create_default_context(), timeout=remaining())
            connection.connect()
            connection.sock.settimeout(remaining())
            self._check_grant(access, operation, binding, purpose)
            if method == "POST":
                if self._now() >= request.deadline:
                    fail("calendar_request_expired")
                authorize()  # current lease/revocation/operation check, after vault and TLS
            self._check_grant(access, operation, binding, purpose)
            connection.sock.settimeout(remaining())
            connection.request(method, path, body=payload, headers={
                "Authorization": "Bearer " + access.access_token, "Accept": "application/json",
                "Content-Type": "application/json", "Accept-Encoding": "identity", "Connection": "close"})
            access = None
            connection.sock.settimeout(remaining())
            transport = connection.sock
            response = connection.getresponse()
            # Missing, deleted, conflicting and denied resources do NOT prove
            # terminal non-application. Never follow a redirect or retry POST.
            if response.status not in ({200, 201} if method == "POST" else {200}):
                return None
            headers = {}
            for key, value in response.getheaders():
                key = key.lower()
                if key in {"content-type", "content-length", "content-encoding", "transfer-encoding"}:
                    if key in headers:
                        fail("calendar_response_headers_invalid")
                    headers[key] = value
            length = headers.get("content-length")
            if (headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                    or headers.get("content-encoding", "identity").lower() != "identity"
                    or headers.get("transfer-encoding", "chunked").lower() != "chunked"
                    or (length is not None and (not re.fullmatch(r"[0-9]{1,6}", length)
                        or not 1 <= int(length) <= MAX_RESPONSE_BYTES or "transfer-encoding" in headers))):
                fail("calendar_response_headers_invalid")
            data = bytearray()
            while True:
                if transport is not None:
                    transport.settimeout(remaining())
                part = response.read1(min(16384, MAX_RESPONSE_BYTES + 1 - len(data)))
                if not part:
                    break
                data.extend(part)
                if len(data) > MAX_RESPONSE_BYTES:
                    fail("calendar_response_too_large")
                if response.isclosed():
                    break
            remaining()
            if length is not None and len(data) != int(length):
                fail("calendar_response_truncated")
            return _json(bytes(data))
        except CapabilityError:
            raise
        except Exception:
            raise CapabilityError("calendar_transport_indeterminate") from None
        finally:
            access = None
            # Cleanup errors must not expose transport/provider exception text.
            for resource in (response, connection):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        pass

    def _observation(self, value, expected, operation, argument_digest):
        def unknown():
            return ProviderObservation(operation, self.provider_id, argument_digest,
                                       "unknown", False, expected["id"])
        if type(value) is not dict:
            return unknown()
        try:
            if (value.get("kind") != "calendar#event" or value.get("id") != expected["id"]
                    or value.get("status") != "confirmed" or value.get("eventType") != "default"
                    or value.get("summary") != expected["summary"]
                    or value.get("visibility") != "private" or value.get("transparency", "opaque") != "opaque"
                    or value.get("attendees", []) != [] or value.get("recurrence", []) != []
                    or value.get("attendeesOmitted", False) is not False
                    or value.get("anyoneCanAddSelf", False) is not False
                    or any(value.get(k) for k in ("recurringEventId", "originalStartTime", "attachments", "conferenceData", "description", "location"))
                    or value.get("guestsCanModify", False) is not False
                    or value.get("guestsCanInviteOthers") is not False
                    or type(value.get("etag")) is not str or not 1 <= len(value["etag"]) <= 256
                    or type(value.get("organizer")) is not dict
                    or value["organizer"].get("email") != self.calendar_id
                    or value["organizer"].get("self") is not True
                    or type(value.get("reminders")) is not dict
                    or value["reminders"].get("useDefault") is not False
                    or value["reminders"].get("overrides", []) != []):
                return unknown()
            properties = value.get("extendedProperties")
            if (type(properties) is not dict or properties.get("private") != expected["extendedProperties"]["private"]
                    or properties.get("shared", {}) != {}):
                return unknown()
            for field in ("start", "end"):
                part = value.get(field)
                if (type(part) is not dict or "date" in part
                        or _instant(part.get("dateTime")) != _instant(expected[field]["dateTime"])):
                    return unknown()
        except (ValueError, TypeError, OverflowError):
            return unknown()
        return ProviderObservation(operation, self.provider_id, argument_digest, "applied", True, expected["id"])
