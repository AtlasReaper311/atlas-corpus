"""Regression lock for the reusable refresh concurrency namespace.

Historical defect (atlas-corpus#6): the reusable refresh-corpus workflow used
the same concurrency group expression as its callers:

    ${{ github.repository }}-refresh-corpus-${{ github.ref }}

Caller and callee therefore waited on one shared GitHub Actions concurrency
group and could deadlock. The repair gave the reusable workflow a distinct
namespace:

    atlas-corpus-reusable-refresh-${{ github.repository }}-${{ github.ref }}
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "refresh-corpus.yml"

SAFE_GROUP = (
    "atlas-corpus-reusable-refresh-${{ github.repository }}-${{ github.ref }}"
)
HISTORICAL_COLLIDING_GROUP = (
    "${{ github.repository }}-refresh-corpus-${{ github.ref }}"
)


class RefreshConcurrencyError(AssertionError):
    """Raised when the reusable refresh concurrency contract is violated."""


def parse_concurrency(text: str) -> tuple[str, bool]:
    """Return (group, cancel_in_progress) from a workflow concurrency block."""
    lines = text.splitlines()
    in_concurrency = False
    concurrency_indent: int | None = None
    group: str | None = None
    cancel_in_progress: bool | None = None

    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))

        if stripped == "concurrency:":
            in_concurrency = True
            concurrency_indent = indent
            continue

        if not in_concurrency or concurrency_indent is None:
            continue

        if indent <= concurrency_indent and not stripped.startswith("-"):
            break

        if stripped.startswith("group:"):
            group = stripped.split(":", 1)[1].strip().strip("\"'")
        elif stripped.startswith("cancel-in-progress:"):
            value = stripped.split(":", 1)[1].strip().lower()
            if value not in {"true", "false"}:
                raise RefreshConcurrencyError(
                    f"cancel-in-progress must be a boolean, observed {value!r}"
                )
            cancel_in_progress = value == "true"

    if group is None:
        raise RefreshConcurrencyError("refresh-corpus workflow missing concurrency.group")
    if cancel_in_progress is None:
        raise RefreshConcurrencyError(
            "refresh-corpus workflow missing concurrency.cancel-in-progress"
        )
    return group, cancel_in_progress


def validate_refresh_concurrency(text: str) -> str:
    group, cancel_in_progress = parse_concurrency(text)

    if group == HISTORICAL_COLLIDING_GROUP:
        raise RefreshConcurrencyError(
            "reusable refresh concurrency group collides with the historical "
            f"caller namespace {HISTORICAL_COLLIDING_GROUP!r}"
        )

    if not group.startswith("atlas-corpus-reusable-refresh-"):
        raise RefreshConcurrencyError(
            "reusable refresh concurrency group must use the distinct "
            "atlas-corpus-reusable-refresh- namespace, "
            f"observed {group!r}"
        )

    if group != SAFE_GROUP:
        raise RefreshConcurrencyError(
            "reusable refresh concurrency group must remain "
            f"{SAFE_GROUP!r}, observed {group!r}"
        )

    if cancel_in_progress is not False:
        raise RefreshConcurrencyError(
            "reusable refresh concurrency must keep cancel-in-progress: false"
        )

    return group


class RefreshConcurrencyTests(unittest.TestCase):
    def test_current_reusable_workflow_uses_distinct_namespace(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        group = validate_refresh_concurrency(text)
        self.assertEqual(SAFE_GROUP, group)
        self.assertNotEqual(HISTORICAL_COLLIDING_GROUP, group)

    def test_historical_colliding_group_is_rejected(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").replace(
            SAFE_GROUP,
            HISTORICAL_COLLIDING_GROUP,
            1,
        )
        with self.assertRaisesRegex(
            RefreshConcurrencyError,
            "collides with the historical caller namespace",
        ):
            validate_refresh_concurrency(text)

    def test_missing_distinct_prefix_is_rejected(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").replace(
            SAFE_GROUP,
            "refresh-${{ github.repository }}-${{ github.ref }}",
            1,
        )
        with self.assertRaisesRegex(
            RefreshConcurrencyError,
            "atlas-corpus-reusable-refresh-",
        ):
            validate_refresh_concurrency(text)

    def test_cancel_in_progress_true_is_rejected(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").replace(
            "cancel-in-progress: false",
            "cancel-in-progress: true",
            1,
        )
        with self.assertRaisesRegex(
            RefreshConcurrencyError,
            "cancel-in-progress: false",
        ):
            validate_refresh_concurrency(text)

    def test_non_vacuity_reverting_historical_protection_fails_on_disk(self) -> None:
        original = WORKFLOW.read_text(encoding="utf-8")
        mutated = original.replace(SAFE_GROUP, HISTORICAL_COLLIDING_GROUP, 1)
        self.assertNotEqual(original, mutated)

        with tempfile.TemporaryDirectory() as value:
            path = Path(value) / "refresh-corpus.yml"
            path.write_text(mutated, encoding="utf-8")
            with self.assertRaisesRegex(
                RefreshConcurrencyError,
                "collides with the historical caller namespace",
            ):
                validate_refresh_concurrency(path.read_text(encoding="utf-8"))

        # Production workflow must remain untouched by the non-vacuity proof.
        self.assertEqual(original, WORKFLOW.read_text(encoding="utf-8"))
        validate_refresh_concurrency(WORKFLOW.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
