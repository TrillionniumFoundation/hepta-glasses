from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class HistoryConsentContractTest(unittest.TestCase):
    def test_history_is_fail_closed_and_user_controlled(self) -> None:
        controller = (
            ROOT / "lib/controllers/evenai_model_controller.dart"
        ).read_text(encoding="utf-8")
        page = (ROOT / "lib/views/even_list_page.dart").read_text(
            encoding="utf-8"
        )
        assistant = (ROOT / "lib/services/evenai.dart").read_text(
            encoding="utf-8"
        )
        privacy = (ROOT / "docs/PRIVACY_MODEL.md").read_text(
            encoding="utf-8"
        )
        flutter_test = (
            ROOT / "test/runtime/even_ai_history_page_test.dart"
        ).read_text(encoding="utf-8")

        required_controller_fragments = (
            "final historyEnabled = false.obs;",
            "if (!historyEnabled.value)",
            "void setHistoryEnabled(bool enabled)",
            "if (!enabled)",
            "clearItems();",
        )
        for fragment in required_controller_fragments:
            self.assertIn(fragment, controller)

        self.assertIn("history-consent-switch", page)
        self.assertIn("onChanged: controller.setHistoryEnabled", page)
        self.assertIn("Off by default", page)
        self.assertNotIn("items.insert", assistant)

        self.assertIn("disabled by default on every application start", privacy)
        self.assertIn("process-memory history only", privacy)
        self.assertIn("disabling history immediately clears", privacy)

        self.assertIn("history is opt-in and defaults to disabled", flutter_test)
        self.assertIn("deletes retained content and selection", flutter_test)
        self.assertIn("history consent control gates and clears", flutter_test)


if __name__ == "__main__":
    unittest.main()
