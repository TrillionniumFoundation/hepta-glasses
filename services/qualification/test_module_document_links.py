from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from services.qualification.module_document_links import (
    MAX_DOCUMENT_BYTES, ModuleLinkError, validate_primary_fragment,
)


class ModuleDocumentLinkTests(unittest.TestCase):
    def check_text(self, text: str, *, reference: str = "docs/guide.md#edge-runtime") -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "guide.md"
            document.write_text(text, encoding="utf-8")
            validate_primary_fragment(document, reference)

    def test_explicit_anchor_binds_a_real_heading(self) -> None:
        self.check_text('<a id="edge-runtime"></a>\n\n<!-- module:edge-runtime -->\n## Edge runtime\n')

    def test_single_quote_anchor_is_supported(self) -> None:
        self.check_text("<a id='edge-runtime'></a>\n## Runtime\n")

    def test_comment_is_not_an_anchor(self) -> None:
        with self.assertRaises(ModuleLinkError):
            self.check_text('<!--\n<a id="edge-runtime"></a>\n-->\n## Runtime\n')

    def test_module_marker_does_not_manufacture_a_link(self) -> None:
        with self.assertRaises(ModuleLinkError):
            self.check_text('<!-- module:edge-runtime -->\n## Runtime\n')

    def test_heading_slug_is_not_a_stable_explicit_anchor(self) -> None:
        with self.assertRaises(ModuleLinkError):
            self.check_text('## Edge runtime\n')

    def test_fenced_code_anchors_do_not_count(self) -> None:
        for fence in ('```', '~~~', '````'):
            with self.subTest(fence=fence), self.assertRaises(ModuleLinkError):
                self.check_text(f'{fence}html\n<a id="edge-runtime"></a>\n## Runtime\n{fence}\n')

    def test_indented_and_inline_code_anchors_do_not_count(self) -> None:
        for anchor in ('    <a id="edge-runtime"></a>', '`<a id="edge-runtime"></a>`'):
            with self.subTest(anchor=anchor), self.assertRaises(ModuleLinkError):
                self.check_text(anchor+'\n## Runtime\n')

    def test_duplicate_ids_fail(self) -> None:
        with self.assertRaises(ModuleLinkError):
            self.check_text('<a id="edge-runtime"></a>\n## One\n<a id="edge-runtime"></a>\n## Two\n')

    def test_anchor_at_end_or_before_prose_fails(self) -> None:
        for suffix in ('', 'Not a heading\n', '<a id="other"></a>\n## Other\n'):
            with self.subTest(suffix=suffix), self.assertRaises(ModuleLinkError):
                self.check_text('<a id="edge-runtime"></a>\n'+suffix)

    def test_malformed_fragment_fails(self) -> None:
        for fragment in ('', 'Edge-runtime', 'edge-runtime#other', '%65dge-runtime', '../runtime'):
            with self.subTest(fragment=fragment), self.assertRaises(ModuleLinkError):
                self.check_text('<a id="edge-runtime"></a>\n## Runtime\n',reference='guide.md#'+fragment)

    def test_linked_document_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'target.md'; target.write_text('<a id="edge-runtime"></a>\n## Runtime\n')
            link = Path(directory)/'link.md';link.symlink_to(target)
            with self.assertRaises(ModuleLinkError):
                validate_primary_fragment(link,'guide.md#edge-runtime')

    def test_oversized_document_fails(self) -> None:
        with self.assertRaises(ModuleLinkError):
            self.check_text(' '*(MAX_DOCUMENT_BYTES+1))

    def test_no_fragment_keeps_existing_path_validation_responsibility(self) -> None:
        validate_primary_fragment(Path('not-read-by-fragment-check.md'),'docs/primary.md')

    def test_all_shared_module_sections_have_stable_heading_bound_targets(self) -> None:
        root = Path(__file__).resolve().parents[2]
        document = root/'docs/MODULE_DEVELOPMENT_GUIDE.md'
        markers = re.findall(r'<!-- module:([a-z0-9-]+) -->',document.read_text(encoding='utf-8'))
        self.assertEqual(len(markers),22)
        self.assertEqual(len(set(markers)),22)
        for module in markers:
            with self.subTest(module=module):
                validate_primary_fragment(document,'docs/MODULE_DEVELOPMENT_GUIDE.md#'+module)


if __name__ == '__main__':
    unittest.main()
