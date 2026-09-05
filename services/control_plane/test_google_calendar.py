"""Real SQLite composition plus Calendar HTTP fixtures, never live account data."""
from __future__ import annotations

import dataclasses
import http.client
import json
import os
import socket
import ssl
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from services.control_plane.capabilities import CapabilityRequest, DecisionLease, RiskTier, TrustClass, canonical_digest
from services.control_plane.durable_capabilities import DurableCapabilityGateway
from services.control_plane.google_calendar import (
    CalendarAccessGrant, GoogleCalendarAdapter, SPEC, SCOPE, MAX_RESPONSE_BYTES,
)
from services.control_plane.capabilities import CapabilityError


class FakeSocket:
    def __init__(self):
        self.closed = False
        self.timeouts = []
    def settimeout(self, seconds):
        if self.closed:
            raise OSError('fixture closed socket')
        self.timeouts.append(seconds)


class FakeResponse:
    def __init__(self, body=b'', status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers
        self.offset = 0
        self.closed = False
        self.socket = None
        self.on_read = lambda: None
    def getheaders(self):
        return self.headers if self.headers is not None else [
            ('Content-Type', 'application/json; charset=UTF-8'), ('Content-Length', str(len(self.body)))]
    def read1(self, count):
        self.on_read()
        part = self.body[self.offset:self.offset+min(1024, count)]
        self.offset += len(part)
        if self.offset == len(self.body):
            self.closed = True
            self.socket.closed = True
        return part
    def isclosed(self):
        return self.closed
    def close(self):
        self.closed = True
        self.socket.closed = True


class FakeConnection:
    def __init__(self, response, on_request=None, on_connect=None):
        self.response = response
        self.sock = self.transport = FakeSocket()
        response.socket = self.sock
        self.closed = False
        self.requests = []
        self.on_request = on_request or (lambda *args: None)
        self.on_connect = on_connect or (lambda: None)
    def connect(self):
        self.on_connect()
    def request(self, method, path, *, body, headers):
        self.requests.append((method, path, body, headers))
        self.on_request(method, path, body, headers)
    def getresponse(self):
        self.sock = None
        return self.response
    def close(self):
        self.closed = True
        self.transport.closed = True


class CalendarFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name)/'capabilities.sqlite')
        self.now = 1000
        self.token = os.urandom(24).hex()  # synthetic, generated only at runtime
        self.grants = []
        self.grant_change = lambda grant: grant
        self.adapter = GoogleCalendarAdapter('fixture-user', 'fixture-google-sub',
            'fixture-calendar@group.calendar.google.com', self.issue_grant, lambda:self.now)
        self.gateway = self.open()
        self.request = CapabilityRequest('r1','t1','fixture-user','d1',SPEC.name,
            {'title':'Inert test event — not user data', 'start_at':2000, 'end_at':2600}, 'k1', 1100, TrustClass.USER)
        self.operation = 'a'*32
        self.authorizations = 0
        self.wire = []

    def issue_grant(self, operation, binding, purpose):
        grant = CalendarAccessGrant(self.adapter.subject, self.adapter.account_id, self.adapter.calendar_id,
            operation, binding, purpose, frozenset({SCOPE}), self.now+30, self.token)
        self.grants.append(grant)
        return self.grant_change(grant)

    def authorize(self):
        self.authorizations += 1

    def open(self, adapter=None):
        adapter = adapter or self.adapter
        g = DurableCapabilityGateway(self.path, clock=lambda:self.now)
        g.register(SPEC, provider_id=adapter.provider_id, adapter=adapter)
        self.addCleanup(g.close)
        return g

    def lease(self, **changes):
        value = DecisionLease('fixture-lease',self.request.subject,self.request.device_id,
            self.request.task_id,self.request.name,canonical_digest(dict(self.request.arguments)),1050,False)
        return dataclasses.replace(value, **changes)

    def body(self, operation=None):
        body = self.adapter._request(self.request, operation or self.operation)[0]
        return dict(body, kind='calendar#event', etag='"fixture-etag"',
                    organizer={'email':self.adapter.calendar_id,'self':True})

    def factory(self, response=None, modify=None, status=200, on_connect=None, on_request=None):
        response = response or FakeResponse(status=status)
        def capture(method, path, raw, headers):
            self.wire.append((method,path,raw,headers))
            if on_request:
                on_request(method,path,raw,headers)
            if not response.body and response.status in (200,201):
                if method=='POST':
                    data = dict(json.loads(raw), kind='calendar#event', etag='"fixture"',
                                organizer={'email':self.adapter.calendar_id,'self':True})
                else:
                    op = self.gateway.store.db.execute('SELECT operation_id FROM hg_capability_operations').fetchone()
                    data = self.body(op[0] if op else self.operation)
                if modify:
                    modify(data)
                response.body = json.dumps(data,ensure_ascii=True).encode()
        conn = FakeConnection(response,capture,on_connect)
        return conn

    def direct(self, **changes):
        args = dict(request=self.request,operation_id=self.operation,authorize=self.authorize)
        args.update(changes)
        return self.adapter.execute_authorized(**args)

    def execute(self, gateway=None, lease=None):
        return (gateway or self.gateway).execute(self.request,lease=lease or self.lease())

    def assert_code(self, expected, function):
        with self.assertRaises(CapabilityError) as error:
            function()
        self.assertEqual(error.exception.code, expected)
        self.assertNotIn(self.token,str(error.exception))
        return error.exception

class CalendarTests(CalendarFixture):
    def test_real_gateway_transaction_precedes_post_and_returns_bound_success(self):
        def check(*args):
            with self.open().store.transaction() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM hg_capability_leases').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT state FROM hg_capability_operations').fetchone()[0],'dispatching')
        conn=self.factory(on_request=check)
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn) as create:
            receipt=self.execute()
        self.assertEqual(receipt.status,'succeeded')
        self.assertFalse(receipt.result['retry_safe'])
        self.assertTrue(conn.closed)
        self.assertTrue(conn.response.closed)
        self.assertEqual(create.call_args.args,('www.googleapis.com',443))
        self.assertTrue(create.call_args.kwargs['context'].check_hostname)
        self.assertEqual(create.call_args.kwargs['context'].verify_mode,ssl.CERT_REQUIRED)

    def test_exact_wire_profile_does_not_send_guests_or_enable_other_features(self):
        conn=self.factory()
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
            self.execute()
        method,path,raw,headers=self.wire[0];body=json.loads(raw)
        self.assertEqual(method,'POST')
        self.assertIn('fixture-calendar%40group.calendar.google.com',path)
        self.assertIn('sendUpdates=none',path)
        self.assertEqual(body['attendees'],[])
        self.assertEqual(body['reminders'],{'useDefault':False})
        self.assertEqual(body['eventType'],'default')
        self.assertEqual(body['visibility'],'private')
        self.assertNotIn('recurrence',body)
        self.assertNotIn('conferenceData',body)
        self.assertEqual(headers['Authorization'],'Bearer '+self.token)
        self.assertNotIn(self.token,raw.decode())
        self.assertRegex(body['id'],r'^h[0-9a-f]{64}$')

    def test_operation_and_route_determine_stable_distinct_event_ids(self):
        a=self.body()['id'];self.assertEqual(a,self.body()['id'])
        self.assertNotEqual(a,self.body('b'*32)['id'])
        other=dataclasses.replace(self.adapter,calendar_id='other@example.com')
        self.assertNotEqual(a,other._request(self.request,self.operation)[0]['id'])
        self.assertNotEqual(other.provider_id,self.adapter.provider_id)

    def test_plaintext_token_title_and_calendar_not_in_database(self):
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory()):
            self.execute()
        for path in Path(self.tmp.name).glob('capabilities.sqlite*'):
            raw=path.read_bytes()
            for marker in (self.token,self.request.arguments['title'],self.adapter.calendar_id,self.adapter.account_id):
                self.assertNotIn(marker.encode(),raw)

    def test_direct_legacy_adapter_execution_is_disabled(self):
        self.assert_code('calendar_revalidating_gateway_required',lambda:self.adapter.execute(self.request,self.operation))

    def test_gateway_registration_cannot_relabel_provider_or_lower_risk(self):
        g=DurableCapabilityGateway(str(Path(self.tmp.name)/'other.sqlite'),clock=lambda:self.now)
        self.addCleanup(g.close)
        self.assert_code('capability_adapter_binding_mismatch',lambda:g.register(SPEC,provider_id='wrong',adapter=self.adapter))
        self.assert_code('capability_adapter_binding_mismatch',lambda:g.register(
            dataclasses.replace(SPEC,risk=RiskTier.R0),provider_id=self.adapter.provider_id,adapter=self.adapter))

    def test_optional_authorized_hook_must_be_callable(self):
        class Invalid:
            execute_authorized=7
            def execute(self,*args):pass
            def readback(self,*args):pass
        self.assert_code('capability_adapter_binding_mismatch',lambda:self.gateway.register(
            dataclasses.replace(SPEC,name='invalid'),provider_id='invalid',adapter=Invalid()))

    def test_without_lease_no_credential_or_network_is_requested(self):
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection') as factory:
            receipt=self.gateway.execute(self.request)
        self.assertEqual(receipt.status,'denied');factory.assert_not_called();self.assertEqual(self.grants,[])

    def test_restart_duplicate_never_reposts(self):
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory()) as factory:
            first=self.execute();second=self.execute(gateway=self.open())
            self.assertEqual(factory.call_count,1)
        self.assertEqual(first.result,second.result);self.assertTrue(second.replayed)

    def test_lost_post_is_read_back_with_same_event_id_without_post_replay(self):
        first=self.factory(status=503)
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=first):
            receipt=self.execute()
        self.assertEqual(receipt.status,'indeterminate')
        event_id=receipt.result['external_id']
        second=self.factory()
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=second):
            recovered=self.open().reconcile(self.request)
        self.assertEqual(recovered.status,'succeeded')
        self.assertTrue(recovered.reconciled)
        self.assertEqual([row[0] for row in self.wire],['POST','GET'])
        self.assertTrue(self.wire[-1][1].endswith(event_id))
        self.assertEqual([grant.purpose for grant in self.grants],['execute','readback'])

    def test_404_410_409_429_and_5xx_never_prove_nonapplication(self):
        for status in (404,410,409,429,500,503,401,403,302):
            with self.subTest(status=status):
                response=FakeResponse(b'private-error-body',status=status)
                conn=self.factory(response)
                with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
                    observation=self.direct()
                self.assertEqual(observation.disposition,'unknown')
                self.assertFalse(observation.terminal)
                self.assertEqual(len(conn.requests),1)
                self.assertEqual(response.offset,0)

    def test_readback_404_remains_unknown_and_never_generates(self):
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(status=503)):
            self.execute()
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(status=404)):
            receipt=self.gateway.reconcile(self.request)
        self.assertEqual(receipt.status,'indeterminate')
        self.assertEqual([r[0] for r in self.wire],['POST','GET'])

    def test_readback_after_original_deadline_needs_new_read_grant_not_mutation(self):
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(status=503)):
            self.execute()
        self.now=1200
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory()):
            receipt=self.gateway.reconcile(self.request)
        self.assertEqual(receipt.status,'succeeded')
        self.assertEqual(self.grants[-1].purpose,'readback')

    def test_revocation_during_vault_callback_prevents_post(self):
        other=self.open()
        def revoke(grant):
            other.revoke_subject(self.request.subject)
            return grant
        self.grant_change=revoke;conn=self.factory()
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
            receipt=self.execute()
        self.assertEqual(receipt.status,'indeterminate');self.assertEqual(conn.requests,[])

    def test_lease_expiry_during_vault_callback_prevents_post(self):
        self.grant_change=lambda grant:(setattr(self,'now',1002) or grant)
        conn=self.factory()
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
            receipt=self.execute(lease=self.lease(expires_at=1001))
        self.assertEqual(receipt.status,'indeterminate');self.assertEqual(conn.requests,[])

    def test_lease_expiry_during_tls_prevents_post(self):
        conn=self.factory(on_connect=lambda:setattr(self,'now',1002))
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
            receipt=self.execute(lease=self.lease(expires_at=1001))
        self.assertEqual(receipt.status,'indeterminate');self.assertEqual(conn.requests,[])

    def test_revoke_during_tls_prevents_post(self):
        conn=self.factory(on_connect=lambda:self.open().revoke_subject(self.request.subject))
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
            self.assertEqual(self.execute().status,'indeterminate')
        self.assertEqual(conn.requests,[])

    def test_revoke_after_post_does_not_falsify_successful_effect(self):
        conn=self.factory(on_request=lambda *args:self.open().revoke_subject(self.request.subject))
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
            self.assertEqual(self.execute().status,'succeeded')

    def test_authorized_readback_after_revoke_preserves_effect_truth(self):
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(status=503)):
            self.execute()
        self.gateway.revoke_subject(self.request.subject)
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory()):
            self.assertEqual(self.gateway.reconcile(self.request).status,'succeeded')
        self.assertEqual(self.grants[-1].purpose,'readback')

    def test_wrong_grant_binding_types_or_scopes_never_send(self):
        for changes in ({'subject':'other'},{'account_id':'other'},{'calendar_id':'other@example.com'},
                {'operation_id':'b'*32},{'request_digest':'b'*64},{'purpose':'readback'},
                {'scopes':frozenset({'https://www.googleapis.com/auth/calendar'})},
                {'scopes':{SCOPE}},{'expires_at':1000},{'expires_at':True}):
            self.grant_change=lambda grant,c=changes:dataclasses.replace(grant,**c)
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection') as factory:
                self.assert_code('calendar_oauth_grant_invalid',self.direct)
                factory.assert_not_called()

    def test_malformed_token_and_header_injection_fail_before_connection(self):
        for value in ('', 'short', 'x'*4097, 'x'*20+'\r\nInjected: yes', '界'*20, None):
            self.grant_change=lambda grant,v=value:dataclasses.replace(grant,access_token=v)
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection') as factory:
                self.assert_code('calendar_oauth_grant_invalid',self.direct)
                factory.assert_not_called()

    def test_grant_expiry_during_tls_is_rechecked(self):
        conn=self.factory(on_connect=lambda:setattr(self,'now',1040))
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
            self.assert_code('calendar_oauth_grant_invalid',self.direct)
        self.assertEqual(conn.requests,[])

    def test_grant_expiry_during_authorization_is_rechecked(self):
        conn=self.factory();calls=[0]
        def authorize():
            calls[0]+=1
            if calls[0]==2:self.now=1040
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
            self.assert_code('calendar_oauth_grant_invalid',lambda:self.direct(authorize=authorize))
        self.assertEqual(conn.requests,[])

    def test_vault_error_and_transport_error_text_are_not_exposed(self):
        self.grant_change=lambda grant:(_ for _ in ()).throw(RuntimeError(self.token))
        error=self.assert_code('calendar_transport_indeterminate',self.direct)
        self.assertTrue(error.__suppress_context__)
        self.grant_change=lambda grant:grant
        conn=self.factory(on_connect=lambda:(_ for _ in ()).throw(RuntimeError(self.token)))
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
            self.assert_code('calendar_transport_indeterminate',self.direct)
        self.assertTrue(conn.closed)

    def test_wrong_provider_event_fields_cannot_promote_success(self):
        cases=[{'id':'h'+'b'*64},{'kind':'calendar#other'},{'status':'cancelled'},{'eventType':'outOfOffice'},
            {'summary':'different'},{'visibility':'public'},{'transparency':'transparent'},
            {'attendees':[{'email':'thirdparty@example.com'}]},{'recurrence':['RRULE:FREQ=DAILY']},
            {'conferenceData':{'id':'unexpected'}},{'attachments':[{'id':'unexpected'}]},
            {'organizer':{'email':'other@example.com','self':True}}, {'organizer':{'email':self.adapter.calendar_id,'self':1}},
            {'reminders':{'useDefault':True}}, {'reminders':{'useDefault':False,'overrides':[{'method':'email','minutes':0}]}},
            {'guestsCanInviteOthers':True},{'guestsCanModify':True},{'etag':None}]
        for changes in cases:
            with self.subTest(changes=changes):
                conn=self.factory(modify=lambda body,c=changes:body.update(c))
                with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
                    observation=self.direct()
                self.assertEqual(observation.disposition,'unknown');self.assertFalse(observation.terminal)

    def test_extended_property_drift_or_forged_marker_alone_is_not_success(self):
        for change in (lambda b:b['extendedProperties']['private'].update(hgArguments='b'*64),
                       lambda b:b['extendedProperties'].update(shared={'unexpected':'value'}),
                       lambda b:b.update(start={'dateTime':'1970-01-01T00:33:21Z'})):
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(modify=change)):
                self.assertEqual(self.direct().disposition,'unknown')

    def test_times_compare_instants_and_reject_naive_allday_fractional_drift(self):
        variants=[({'dateTime':'1970-01-01T01:33:20+01:00'},True),
                  ({'dateTime':'1970-01-01T00:33:20.000000Z'},True),
                  ({'dateTime':'1970-01-01T00:33:20'},False),
                  ({'dateTime':'1970-01-01T00:33:20.1Z'},False),
                  ({'dateTime':'1970-01-01T00:33:20-00:00'},False),
                  ({'date':'1970-01-01'},False)]
        for start,expected in variants:
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(modify=lambda b,s=start:b.update(start=s))):
                self.assertEqual(self.direct().terminal,expected)

    def test_input_bounding_no_injected_attendee_calendar_or_recurrence(self):
        for changes in ({'attendees':[]},{'calendar_id':'other'},{'recurrence':[]},
                        {'start_at':True},{'end_at':2000},{'end_at':2000+86401},
                        {'title':'x'*257},{'title':'\ud800'},{'title':'line\nbreak'}):
            req=dataclasses.replace(self.request,arguments={**self.request.arguments,**changes})
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection') as factory:
                with self.assertRaises(CapabilityError):self.direct(request=req)
                factory.assert_not_called()

    def test_config_is_immutable_and_primary_or_path_injection_is_disallowed(self):
        for value in ('primary','PRIMARY','a/b','a?x=1','a%40b','a\r\n', 'x'*257):
            self.assert_code('calendar_configuration_invalid',lambda:dataclasses.replace(self.adapter,calendar_id=value))
        with self.assertRaises(dataclasses.FrozenInstanceError):self.adapter.calendar_id='other'
        self.assertNotIn(self.token,repr(self.adapter));self.assertNotIn(self.adapter.calendar_id,repr(self.adapter))

    def test_request_and_operation_binding_rejected(self):
        for req in (dataclasses.replace(self.request,subject='other'),dataclasses.replace(self.request,name='other'),dataclasses.replace(self.request,deadline=True)):
            self.assert_code('calendar_request_binding_invalid',lambda:self.direct(request=req))
        for operation in ('../event','b'*64,'A'*32,''):
            self.assert_code('calendar_request_binding_invalid',lambda:self.direct(operation_id=operation))

    def test_readback_external_id_cannot_choose_another_resource(self):
        self.assert_code('calendar_external_id_mismatch',lambda:self.adapter.readback(self.request,self.operation,'another'))

    def test_invalid_clock_fails_without_side_effect(self):
        self.now=True
        self.assert_code('calendar_clock_invalid',self.direct)

    def test_no_proxy_or_environment_route_override(self):
        conn=self.factory()
        with patch.dict(os.environ,{'HTTPS_PROXY':'https://attacker.invalid','GOOGLE_CALENDAR_BASE_URL':'https://attacker.invalid'}):
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn) as factory:
                self.direct()
        self.assertEqual(factory.call_args.args,('www.googleapis.com',443))

    def test_readback_budget_persists_across_restart(self):
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(status=503)):
            self.execute()
        for _ in range(8):
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(status=404)):
                self.assertEqual(self.open().reconcile(self.request).status,'indeterminate')
        self.assert_code('capability_readback_capacity_exhausted',lambda:self.open().reconcile(self.request))
        self.assertEqual(sum(x[0]=='POST' for x in self.wire),1)

    def test_concurrent_duplicate_only_one_post(self):
        entered,release=threading.Event(),threading.Event()
        results=[]
        def pause(*args):entered.set();release.wait(2)
        conn=self.factory(on_request=pause)
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=conn):
            t=threading.Thread(target=lambda:results.append(self.execute()));t.start()
            try:
                self.assertTrue(entered.wait(1))
                duplicate=self.execute(gateway=self.open())
                self.assertTrue(duplicate.replayed);self.assertEqual(duplicate.status,'indeterminate')
            finally:
                release.set();t.join(3)
        self.assertFalse(t.is_alive());self.assertEqual(len(conn.requests),1)
        self.assertEqual(results[0].status,'succeeded')

    def test_oversized_and_duplicate_json_never_promote(self):
        for raw in (b'{"id":1,"id":2}',b'{"x":NaN}',b'[]',b'\xff',b'['*1100):
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(FakeResponse(raw))):
                self.assert_code('calendar_response_json_invalid',self.direct)
        response=FakeResponse(b'x'*(MAX_RESPONSE_BYTES+100),headers=[('Content-Type','application/json')])
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(response)):
            self.assert_code('calendar_response_too_large',self.direct)
        self.assertEqual(response.offset,MAX_RESPONSE_BYTES+1)

    def test_header_ambiguity_compression_and_size_are_rejected(self):
        body=json.dumps(self.body()).encode()
        cases=[ [('Content-Type','application/json'),('Content-Type','application/json')],
                [('Content-Type','text/html')], [('Content-Type','application/json'),('Content-Encoding','gzip')],
                [('Content-Type','application/json'),('Transfer-Encoding','evil')],
                [('Content-Type','application/json'),('Content-Length','1'),('Transfer-Encoding','chunked')],
                [('Content-Type','application/json'),('Content-Length','999999')],
                [('Content-Type','application/json'),('Content-Length','-1')]]
        for headers in cases:
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(FakeResponse(body,headers=headers))):
                self.assert_code('calendar_response_headers_invalid',self.direct)

    def test_truncated_body_is_not_success(self):
        raw=json.dumps(self.body()).encode()
        headers=[('Content-Type','application/json'),('Content-Length',str(len(raw)+1))]
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(FakeResponse(raw,headers=headers))):
            self.assert_code('calendar_response_truncated',self.direct)

    def test_monotonic_timeout_covers_vault_and_response_processing(self):
        now=[0.0]
        self.grant_change=lambda grant:(now.__setitem__(0,10.0) or grant)
        with patch('services.control_plane.google_calendar.time.monotonic',side_effect=lambda:now[0]):
            self.assert_code('calendar_transport_deadline',self.direct)
        now[0]=0;self.grant_change=lambda grant:grant
        response=FakeResponse(json.dumps(self.body()).encode());response.on_read=lambda:now.__setitem__(0,10.0)
        with patch('services.control_plane.google_calendar.time.monotonic',side_effect=lambda:now[0]):
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=self.factory(response)):
                self.assert_code('calendar_transport_deadline',self.direct)

def _raw_exchange(test, wire):
    # No internet or TLS bypass: this test replaces the transport with a local
    # socketpair only, exercising the actual stdlib HTTP parser.
    client,server=socket.socketpair()
    failures=[]
    def serve():
        try:
            pending=b''
            while b'\r\n\r\n' not in pending:pending+=server.recv(4096)
            header,body=pending.split(b'\r\n\r\n',1)
            length=0
            for line in header.split(b'\r\n'):
                if line.lower().startswith(b'content-length:'):length=int(line.split(b':',1)[1])
            while len(body)<length:body+=server.recv(4096)
            server.sendall(wire)
        except (BrokenPipeError,ConnectionResetError):pass
        except BaseException as error:failures.append(type(error).__name__)
        finally:server.close()
    thread=threading.Thread(target=serve);thread.start()
    real=http.client.HTTPConnection('socketpair-fixture')
    real.connect=lambda:setattr(real,'sock',client)
    try:
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection',return_value=real):
            return test.direct()
    finally:
        real.close();client.close();thread.join(3)
        test.assertFalse(thread.is_alive());test.assertEqual(failures,[])



class RealHTTPTests(CalendarFixture):
    def test_real_http_content_length(self):
        body=json.dumps(self.body()).encode()
        wire=(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '
              +str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
        self.assertTrue(_raw_exchange(self,wire).terminal)

    def test_real_http_chunked(self):
        body=json.dumps(self.body()).encode()
        wire=(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n'
              +hex(len(body))[2:].encode()+b'\r\n'+body+b'\r\n0\r\n\r\n')
        self.assertTrue(_raw_exchange(self,wire).terminal)

    def test_real_http_close_delimited(self):
        body=json.dumps(self.body()).encode()
        wire=b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n'+body
        self.assertTrue(_raw_exchange(self,wire).terminal)

    def test_real_http_truncated_content_length(self):
        body=json.dumps(self.body()).encode()
        wire=(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '
              +str(len(body)+1).encode()+b'\r\nConnection: close\r\n\r\n'+body)
        with self.assertRaises(CapabilityError):_raw_exchange(self,wire)

    def test_real_http_truncated_chunk(self):
        body=json.dumps(self.body()).encode()
        wire=(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n'
              +hex(len(body))[2:].encode()+b'\r\n'+body)
        with self.assertRaises(CapabilityError):_raw_exchange(self,wire)

    def test_real_http_duplicate_content_length(self):
        body=json.dumps(self.body()).encode()
        wire=(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '
              +str(len(body)).encode()+b'\r\nContent-Length: '+str(len(body)).encode()
              +b'\r\nConnection: close\r\n\r\n'+body)
        with self.assertRaises(CapabilityError):_raw_exchange(self,wire)



class CalendarFinalObservationTests(CalendarFixture):
    def test_omitted_attendees_never_prove_no_guests(self):
        for marker in (True, 1, 'true'):
            conn = self.factory(modify=lambda value, m=marker: value.update(attendeesOmitted=m))
            with patch('services.control_plane.google_calendar.http.client.HTTPSConnection', return_value=conn):
                result = self.direct()
            self.assertEqual(result.disposition, 'unknown')
            self.assertFalse(result.terminal)

    def test_open_self_invitation_not_accepted(self):
        conn = self.factory(modify=lambda value: value.update(anyoneCanAddSelf=True))
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection', return_value=conn):
            self.assertEqual(self.direct().disposition, 'unknown')

    def test_explicit_complete_guest_view_remains_valid(self):
        conn = self.factory(modify=lambda value: value.update(attendeesOmitted=False, anyoneCanAddSelf=False))
        with patch('services.control_plane.google_calendar.http.client.HTTPSConnection', return_value=conn):
            self.assertEqual(self.direct().disposition, 'applied')

    def test_invalid_offset_minutes_rejected(self):
        from services.control_plane.google_calendar import _instant
        for value in ('2026-09-05T00:00:00+00:60', '2026-09-05T00:00:00-00:60', '2026-09-05T00:00:00+24:00'):
            self.assert_code('calendar_event_time_invalid', lambda v=value: _instant(v))

if __name__=='__main__':unittest.main()
