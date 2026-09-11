"""Exact Calendar source slots and import fences, with inert scanner fixtures."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from tools.server_provider_boundary import (
    CONTRACT, ServerProviderBoundary, _CALENDAR, _CALENDAR_TEST, _CALENDAR_PATTERN,
    _PROVIDER, _TEST, read_regular,
)

ROOT = Path(__file__).resolve().parents[2]


class CalendarProviderBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.declaration = json.loads((ROOT / CONTRACT).read_text())
        for row in self.declaration['entries']:
            self.write(row['path'], (ROOT / row['path']).read_bytes())
        self.save()

    def write(self, path, raw):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return target

    def save(self):
        self.write(CONTRACT, (json.dumps(self.declaration, indent=2) + '\n').encode())

    def marker(self):
        # Derive a synthetic scanner input, never a network endpoint override.
        return _CALENDAR_PATTERN.pattern.replace(r'\.', '.')

    def scanner(self):
        return ServerProviderBoundary(self.root)

    def test_exact_four_declared_files_are_required_and_accepted(self):
        scanner = self.scanner()
        self.assertEqual(set(scanner.hashes), {_PROVIDER, _TEST, _CALENDAR, _CALENDAR_TEST})
        for path in scanner.hashes:
            self.assertEqual(scanner.inspect(path, read_regular(self.root, path), {}), [])
        scanner.finish()

    def test_google_marker_checked_even_with_empty_caller_patterns(self):
        self.assertTrue(self.scanner().inspect('lib/client.dart', self.marker().encode(), {}))

    def test_copied_calendar_bytes_rejected_in_all_six_roots(self):
        data = (self.root / _CALENDAR).read_bytes()
        for root, suffix in [('lib', '.dart'), ('android', '.kt'), ('ios', '.swift'),
                             ('services', '.py'), ('adapters', '.py'), ('plugins', '.py')]:
            with self.subTest(root=root):
                errors = self.scanner().inspect(root + '/copied' + suffix, data, {})
                self.assertTrue(any('calendar provider endpoint' in error for error in errors))

    def test_unregistered_control_plane_file_has_no_host_exception(self):
        self.assertTrue(self.scanner().inspect('services/control_plane/other.py',
            ('HOST = ' + repr(self.marker()) + '\n').encode(), {}))

    def test_calendar_hash_drift_rejected(self):
        for path in (_CALENDAR, _CALENDAR_TEST):
            with self.assertRaisesRegex(AssertionError, 'digest_mismatch'):
                self.scanner().inspect(path, (self.root / path).read_bytes() + b'\n', {})

    def test_calendar_role_cannot_be_widened(self):
        self.declaration['entries'][2]['role'] = 'wire_regression'
        self.save()
        with self.assertRaisesRegex(AssertionError, 'entry_invalid'):
            self.scanner()

    def test_missing_calendar_declaration_rejected(self):
        self.declaration['entries'].pop()
        self.save()
        with self.assertRaises(AssertionError):
            self.scanner()

    def test_calendar_wildcard_path_rejected(self):
        self.declaration['entries'][2]['path'] = 'services/control_plane/*'
        self.save()
        with self.assertRaisesRegex(AssertionError, 'entry_invalid'):
            self.scanner()

    def test_existing_pattern_categories_still_checked_in_calendar_slot(self):
        path = _CALENDAR
        data = (self.root / path).read_bytes() + b'\n# INERT_NEGATIVE_PATTERN\n'
        next(row for row in self.declaration['entries'] if row['path'] == path)['sha256'] = hashlib.sha256(data).hexdigest()
        self.save()
        errors = self.scanner().inspect(path, data, {'inert negative category': re.compile('INERT_NEGATIVE_PATTERN')})
        self.assertEqual(errors, ['inert negative category: ' + path])

    def test_consumer_absolute_and_package_imports_rejected(self):
        for text in ('import services.control_plane.google_calendar as c\n',
                     'from services.control_plane import google_calendar\n',
                     'from services.control_plane.google_calendar import GoogleCalendarAdapter\n',
                     'from services.control_plane import *\n'):
            self.assertTrue(self.scanner().inspect('adapters/client.py', text.encode(), {}))

    def test_relative_calendar_import_outside_owner_rejected(self):
        self.assertTrue(self.scanner().inspect('services/model_gateway/client.py',
            b'from ..control_plane.google_calendar import GoogleCalendarAdapter\n', {}))

    def test_calendar_service_does_not_gain_model_import_permission(self):
        self.assertTrue(self.scanner().inspect('services/control_plane/client.py',
            b'from ..model_gateway.responses_provider import ResponsesProvider\n', {}))

    def test_owner_service_imports_are_valid(self):
        self.assertEqual(self.scanner().inspect('services/control_plane/client.py',
            b'from .google_calendar import GoogleCalendarAdapter\n', {}), [])
        self.assertEqual(self.scanner().inspect('services/model_gateway/client.py',
            b'from .responses_provider import ResponsesProvider\n', {}), [])

    def test_all_declared_sources_must_be_seen(self):
        scanner = self.scanner()
        for path in (_PROVIDER, _TEST):
            scanner.inspect(path, (self.root / path).read_bytes(), {})
        with self.assertRaisesRegex(AssertionError, 'not_scanned'):
            scanner.finish()

    def test_calendar_symlink_rejected(self):
        path = self.root / _CALENDAR
        original = self.root / 'actual.py'
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaises(AssertionError):
            read_regular(self.root, _CALENDAR)

    def test_malformed_python_is_not_import_permission(self):
        with self.assertRaisesRegex(AssertionError, 'parse_failed'):
            self.scanner().inspect('services/control_plane/client.py', b'def bad(:\n', {})


if __name__ == '__main__':
    unittest.main()
