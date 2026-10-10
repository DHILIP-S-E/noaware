"""Change Classification Engine for NowAware."""

import re
from typing import List, Optional
from src.schemas.changes import (
    ClassificationType,
    ConfidenceLevel,
    ChangeAnalysisResult,
)
from src.schemas.monitoring import MonitoringRule
from src.monitoring.diff_engine import DiffResult


class ChangeClassifier:
    """Classifies differences against the user's monitoring criteria."""

    # Patterns representing trivial noise, layout, or page boilerplate
    NOISE_PATTERNS = [
        re.compile(r"^©\s*\d{4}", re.IGNORECASE),
        re.compile(r"copyright\s+\d{4}", re.IGNORECASE),
        re.compile(r"all rights reserved", re.IGNORECASE),
        re.compile(r"terms of use|privacy policy", re.IGNORECASE),
        re.compile(r"page views?:\s*\d+", re.IGNORECASE),
        re.compile(r"last generated|built with|rendered at", re.IGNORECASE),
        re.compile(r"session[-_]?id", re.IGNORECASE),
        re.compile(r"cookies?|accept all", re.IGNORECASE),
        re.compile(r"navigation|search\s*\|\s*portals?", re.IGNORECASE),
        re.compile(r"built with\s+v?[\d\.]+", re.IGNORECASE),
    ]

    DATE_PATTERNS = [
        re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b", re.IGNORECASE),
        re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
        re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
        re.compile(r"\b(?:deadline|due date|closing date|cutoff|extended to|open until)\b", re.IGNORECASE),
    ]

    REQUIREMENT_PATTERNS = [
        re.compile(r"\b(?:eligib|require|prerequisit|qualif|minimum gpa|citizenship|criteria|mandatory)\b", re.IGNORECASE),
        re.compile(r"\b(?:must be|applicants must|shall submit|documents required)\b", re.IGNORECASE),
    ]

    NUMERICAL_FEE_PATTERNS = [
        re.compile(r"\$\s*\d+(?:\.\d{2})?"),
        re.compile(r"\b(?:fee|tuition|cost|price|award|grant|stipend|amount):\s*\$?\d+", re.IGNORECASE),
    ]

    @classmethod
    def classify_diff(
        cls,
        rule: MonitoringRule,
        diff_result: DiffResult,
        source_url: str = "",
    ) -> ChangeAnalysisResult:
        """
        Deterministically evaluates whether the difference matches the user's rule criteria.
        """
        if not diff_result.has_changed:
            return ChangeAnalysisResult(
                change_detected=False,
                classification=ClassificationType.IRRELEVANT,
                summary="No changes detected in source content.",
                previous_value=None,
                new_value=None,
                impact_explanation="The retrieved source content matches the established baseline exactly.",
                evidence=[],
                source_url=source_url,
                confidence=ConfidenceLevel.VERIFIED,
                recommended_action="No action required.",
                should_notify=False,
            )

        all_added = " ".join(diff_result.added_lines)
        all_removed = " ".join(diff_result.removed_lines)
        combined_diff_text = f"{all_added} {all_removed}"

        # 1. Check if change is solely pure noise
        is_only_noise = cls._check_pure_noise(diff_result.added_lines, diff_result.removed_lines)
        if is_only_noise:
            return ChangeAnalysisResult(
                change_detected=True,
                classification=ClassificationType.IRRELEVANT,
                summary="Minor formatting, copyright, or telemetry updates detected.",
                previous_value=diff_result.isolated_previous,
                new_value=diff_result.isolated_new,
                impact_explanation="The detected edit only affects page footer, layout, or cosmetic metadata without altering substantive information.",
                evidence=diff_result.evidence_snippets[:3],
                source_url=source_url,
                confidence=ConfidenceLevel.VERIFIED,
                recommended_action="No action needed. Monitored substantive criteria remain unchanged.",
                should_notify=False,
            )

        # 2. Evaluate against user's specific categories & natural language goal
        goal_lower = rule.natural_language_goal.lower()
        instructions_lower = (rule.specific_instructions or "").lower()
        categories = [c.lower() for c in rule.criteria_categories]

        is_date_monitoring = any("date" in c or "deadline" in c for c in categories) or any(
            w in goal_lower for w in ["deadline", "date", "due", "closing", "cutoff", "when"]
        )
        is_req_monitoring = any("eligib" in c or "require" in c for c in categories) or any(
            w in goal_lower for w in ["requirement", "eligible", "eligibility", "criteria", "rule", "gpa"]
        )
        is_fee_monitoring = any("price" in c or "fee" in c or "cost" in c for c in categories) or any(
            w in goal_lower for w in ["fee", "price", "cost", "tuition", "amount", "rate"]
        )
        is_announcement_monitoring = any("announcement" in c or "feed" in c for c in categories) or any(
            phrase in goal_lower for phrase in [
                "new announcement", "new opportunity", "new post", "feed publishes",
                "track feed", "track this rss", "published"
            ]
        )

        matched_substance = False
        match_reason = ""
        evidence = diff_result.evidence_snippets

        # Test Date / Deadline Change
        if is_date_monitoring:
            has_date_term = any(p.search(combined_diff_text) for p in cls.DATE_PATTERNS)
            if has_date_term:
                matched_substance = True
                match_reason = "Identified deadline or date alteration affecting application or submission timeline."

        # Test Eligibility / Requirements Change
        if is_req_monitoring:
            has_req_term = any(p.search(combined_diff_text) for p in cls.REQUIREMENT_PATTERNS)
            if has_req_term:
                matched_substance = True
                match_reason = "Identified modification to eligibility requirements, criteria, or prerequisite rules."

        # Test Fee / Price Change
        if is_fee_monitoring:
            has_fee_term = any(p.search(combined_diff_text) for p in cls.NUMERICAL_FEE_PATTERNS)
            if has_fee_term:
                matched_substance = True
                match_reason = "Identified modification to fees, tuition, or financial amounts."

        # Test Feed / Announcement Change
        if is_announcement_monitoring:
            if "ENTRY" in combined_diff_text or "TITLE:" in combined_diff_text:
                matched_substance = True
                match_reason = "Identified newly published announcement or opportunity entry."
            elif any(
                re.search(r"\b(?:announc|new opportunity|solicitation|call for proposals|notice of funding)\b", line, re.IGNORECASE)
                for line in diff_result.added_lines
            ):
                matched_substance = True
                match_reason = "Identified newly published announcement on the page."

        # Test Custom keywords from specific instructions
        if rule.specific_instructions:
            custom_terms = [t.strip().lower() for t in rule.specific_instructions.split(",") if t.strip()]
            for term in custom_terms:
                if term in combined_diff_text.lower():
                    matched_substance = True
                    match_reason = f"Identified change matching monitored keyword '{term}'."
                    break

        if matched_substance:
            summary = f"Noticeable change detected: {diff_result.isolated_new or 'Content updated'}"
            if "deadline" in goal_lower or "date" in goal_lower:
                summary = f"Deadline / date updated: {diff_result.isolated_previous or 'Previous date'} -> {diff_result.isolated_new or 'New date'}"

            return ChangeAnalysisResult(
                change_detected=True,
                classification=ClassificationType.MEANINGFUL,
                summary=summary,
                previous_value=diff_result.isolated_previous,
                new_value=diff_result.isolated_new,
                impact_explanation=f"{match_reason} Directly impacts your monitoring objective: '{rule.natural_language_goal}'.",
                evidence=evidence[:6],
                source_url=source_url,
                confidence=ConfidenceLevel.VERIFIED,
                recommended_action=cls._recommend_action(rule, diff_result),
                should_notify=True,
            )

        # Check if the diff touches partially on criteria keywords or ambiguous phrases
        ambiguous_keywords = ["schedule", "timing", "calendar", "restructuring", "handbook", "policy", "amend", "criteria"]
        is_ambiguous = any(w in combined_diff_text.lower() for w in ambiguous_keywords)

        if is_ambiguous:
            return ChangeAnalysisResult(
                change_detected=True,
                classification=ClassificationType.UNCERTAIN,
                summary="Ambiguous changes detected in source page body.",
                previous_value=diff_result.isolated_previous,
                new_value=diff_result.isolated_new,
                impact_explanation="Source content was modified with related phrasing, but without explicit verified values matching your primary criteria. Flagged for review.",
                evidence=evidence[:4],
                source_url=source_url,
                confidence=ConfidenceLevel.MEDIUM,
                recommended_action="Review source to verify if the modified page sections affect your needs.",
                should_notify=False,  # Quiet by default: uncertain changes kept in inbox for review
            )

        # Unrelated changes -> Irrelevant
        return ChangeAnalysisResult(
            change_detected=True,
            classification=ClassificationType.IRRELEVANT,
            summary="Unrelated modifications detected on page.",
            previous_value=diff_result.isolated_previous,
            new_value=diff_result.isolated_new,
            impact_explanation=f"Text on the page was modified, but does not alter your specific monitored criteria: '{rule.natural_language_goal}'.",
            evidence=evidence[:3],
            source_url=source_url,
            confidence=ConfidenceLevel.VERIFIED,
            recommended_action="No action required. Your monitored items remain unaffected.",
            should_notify=False,
        )

    @classmethod
    def _check_pure_noise(cls, added: List[str], removed: List[str]) -> bool:
        """Returns True if every added and removed line matches noise patterns or has negligible semantic value."""
        all_lines = added + removed
        if not all_lines:
            return False

        noise_matches = 0
        for line in all_lines:
            line_str = line.strip()
            # If extremely short or matches noise regex
            if len(line_str) <= 3:
                noise_matches += 1
                continue
            if any(p.search(line_str) for p in cls.NOISE_PATTERNS):
                noise_matches += 1
                continue
            # Check for pure number or timestamp line
            if re.match(r"^[\d\s:\.\-\/TZ\+]+$", line_str):
                noise_matches += 1
                continue

        return noise_matches == len(all_lines)

    @staticmethod
    def _recommend_action(rule: MonitoringRule, diff_result: DiffResult) -> str:
        goal_lower = rule.natural_language_goal.lower()
        if "deadline" in goal_lower or "date" in goal_lower:
            return "Review your submission calendar and adjust your schedule for the new deadline."
        if "eligibility" in goal_lower or "require" in goal_lower:
            return "Review the revised qualification requirements to ensure you remain compliant."
        if "feed" in goal_lower or "announcement" in goal_lower or "opportunity" in goal_lower:
            return "Inspect the new announcement posting to see if you qualify to apply."
        return "Review the source link and confirm the updated details."
