#!/usr/bin/env python3
"""Execute the response-authority remediation with unique structural anchors."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(message)


def main() -> int:
    if len(sys.argv) != 2:
        fail("usage: run_response_authority_patch.py REPOSITORY_ROOT")

    root = Path(sys.argv[1]).resolve()
    driver = Path(__file__).with_name("apply_response_authority.py")
    spec = importlib.util.spec_from_file_location("response_authority_driver", driver)
    if spec is None or spec.loader is None:
        fail("unable to load response-authority driver")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    transform_index = 0

    def structural_replace(
        target_root: Path,
        relative: str,
        old: str,
        new: str,
    ) -> None:
        nonlocal transform_index
        transform_index += 1
        text = module.read(target_root, relative)
        exact_count = text.count(old)
        label = old.splitlines()[0] if old.splitlines() else old
        if exact_count == 1:
            print(
                f"TRANSFORM {transform_index:02d} {relative}: exact {label!r}",
                flush=True,
            )
            module.write(target_root, relative, text.replace(old, new, 1))
            return
        if exact_count > 1:
            fail(
                f"{relative}: transform {transform_index} exact anchor is ambiguous "
                f"({exact_count} matches): {label!r}"
            )

        tokens = old.split()
        if not tokens:
            fail(f"{relative}: transform {transform_index} has an empty anchor")
        pattern = r"\s+".join(re.escape(token) for token in tokens)
        matches = list(re.finditer(pattern, text, flags=re.DOTALL))
        if len(matches) != 1:
            fail(
                f"{relative}: transform {transform_index} structural anchor "
                f"matched {len(matches)} times: {label!r}"
            )
        match = matches[0]
        print(
            f"TRANSFORM {transform_index:02d} {relative}: structural {label!r}",
            flush=True,
        )
        module.write(
            target_root,
            relative,
            text[: match.start()] + new + text[match.end() :],
        )

    module.replace_once = structural_replace
    sys.argv = [str(driver), str(root)]
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
