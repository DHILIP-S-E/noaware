"""Diff Engine for Detecting Meaningful Text and Feed Differences."""

import difflib
import re
from typing import List, Dict, Any, Optional, Tuple


class DiffResult:
    """Encapsulates structured differences between baseline and new version."""

    def __init__(
        self,
        has_changed: bool,
        diff_unified: str,
        added_lines: List[str],
        removed_lines: List[str],
        isolated_previous: Optional[str] = None,
        isolated_new: Optional[str] = None,
        evidence_snippets: Optional[List[str]] = None,
    ):
        self.has_changed = has_changed
        self.diff_unified = diff_unified
        self.added_lines = added_lines
        self.removed_lines = removed_lines
        self.isolated_previous = isolated_previous
        self.isolated_new = isolated_new
        self.evidence_snippets = evidence_snippets or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_changed": self.has_changed,
            "added_lines": self.added_lines,
            "removed_lines": self.removed_lines,
            "isolated_previous": self.isolated_previous,
            "isolated_new": self.isolated_new,
            "evidence_snippets": self.evidence_snippets,
            "diff_snippet": self.diff_unified[:1500],
        }


class DiffEngine:
    """Computes differences between previous normalized baseline and current content."""

    @staticmethod
    def compute_diff(baseline_text: str, current_text: str) -> DiffResult:
        """
        Calculates line-by-line diff, isolating changed snippets and candidate before/after values.
        """
        baseline_lines = [l.strip() for l in baseline_text.splitlines() if l.strip()]
        current_lines = [l.strip() for l in current_text.splitlines() if l.strip()]

        if baseline_lines == current_lines:
            return DiffResult(
                has_changed=False,
                diff_unified="",
                added_lines=[],
                removed_lines=[],
            )

        diff = list(
            difflib.unified_diff(
                baseline_lines,
                current_lines,
                fromfile="baseline",
                tofile="current",
                lineterm="",
                n=2,
            )
        )

        added: List[str] = []
        removed: List[str] = []
        evidence: List[str] = []

        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                cleaned = line[1:].strip()
                if cleaned:
                    added.append(cleaned)
                    evidence.append(f"[NEW] {cleaned}")
            elif line.startswith("-") and not line.startswith("---"):
                cleaned = line[1:].strip()
                if cleaned:
                    removed.append(cleaned)
                    evidence.append(f"[OLD] {cleaned}")

        # Attempt to isolate matching replacement values (e.g. date replacement or fee change)
        isolated_prev, isolated_new = DiffEngine._find_isolated_change(removed, added)

        unified_str = "\n".join(diff)

        return DiffResult(
            has_changed=True,
            diff_unified=unified_str,
            added_lines=added,
            removed_lines=removed,
            isolated_previous=isolated_prev,
            isolated_new=isolated_new,
            evidence_snippets=evidence[:10],
        )

    @staticmethod
    def _find_isolated_change(
        removed: List[str], added: List[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Looks for the most salient pair of removed vs added lines with high similarity or shared keywords.
        """
        if not removed and added:
            return None, added[0] if len(added) == 1 else f"{len(added)} new items added"
        if removed and not added:
            return removed[0] if len(removed) == 1 else f"{len(removed)} items removed", None

        # Check for direct pairing (e.g., exactly 1 line changed or highest ratio)
        best_ratio = 0.0
        best_pair = (None, None)

        for rem in removed:
            for add in added:
                ratio = difflib.SequenceMatcher(None, rem, add).ratio()
                if ratio > 0.4 and ratio > best_ratio:
                    best_ratio = ratio
                    best_pair = (rem, add)

        if best_pair[0] is not None:
            return best_pair

        # Fallback to first line of each if available
        first_rem = removed[0] if removed else None
        first_add = added[0] if added else None
        return first_rem, first_add
