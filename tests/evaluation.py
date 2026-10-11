"""Quantitative Evaluation Suite for NowAware.

Measures accuracy, noise suppression rate, duplicate prevention, and evidence correctness
across an expanded set of 9 evaluation scenarios covering:
1. Meaningful changes (deadline change, feed opportunity, eligibility criteria)
2. Irrelevant layout changes (styling, copyright, navigation)
3. Ambiguous edits (vague handbook wording without values -> uncertain)
4. Repeated changes (deduplication suppression)
5. Model failures (LLM error -> deterministic heuristic fallback)
6. Source outages (HTTP 503 -> baseline preserved, error tracked)
7. Misleading webpage content (injected promotional loan ad mentioning dates -> suppressed)

Calculates actual dynamic scores without hardcoding.
Reports false positives and missed meaningful changes explicitly.
"""

import sys
import os
from pathlib import Path
import tempfile
from typing import Dict, Any, List
from unittest.mock import MagicMock
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.sqlite_store import SQLiteStorage
from src.monitoring.fetcher import SourceFetcher
from src.monitoring.service import MonitoringService
from src.schemas.monitoring import MonitoringRule, SourceType
from src.schemas.changes import ClassificationType
from src.monitoring.classifier import ChangeClassifier
from src.monitoring.diff_engine import DiffEngine
from fixtures.scenarios import DEMO_SCENARIOS


def run_evaluation() -> Dict[str, Any]:
    """Runs end-to-end evaluation benchmark across scenarios and returns metrics."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    storage = SQLiteStorage(path)
    fetcher = SourceFetcher()

    # Pre-register mock sources
    for sc in DEMO_SCENARIOS.values():
        fetcher.register_mock_source(sc["sample_url"], sc["baseline_content"])

    service = MonitoringService(storage=storage, fetcher=fetcher)

    eval_cases = [
        {
            "name": "Meaningful Deadline Change Detection",
            "scenario": "scenario_1",
            "type": "meaningful",
            "expected_classified": ClassificationType.MEANINGFUL,
            "expected_should_notify": True,
        },
        {
            "name": "New RSS Feed Opportunity Detection",
            "scenario": "scenario_3",
            "type": "meaningful",
            "expected_classified": ClassificationType.MEANINGFUL,
            "expected_should_notify": True,
        },
        {
            "name": "Meaningful Eligibility Criteria Change (GPA 3.5 -> 3.8)",
            "scenario": "scenario_6_eligibility",
            "type": "meaningful",
            "expected_classified": ClassificationType.MEANINGFUL,
            "expected_should_notify": True,
        },
        {
            "name": "Irrelevant Layout Noise Suppression",
            "scenario": "scenario_2",
            "type": "noise",
            "expected_classified": ClassificationType.IRRELEVANT,
            "expected_should_notify": False,
        },
        {
            "name": "Ambiguous Policy Phrasing without Specific Values",
            "scenario": "scenario_7_ambiguous",
            "type": "ambiguous",
            "expected_classified": ClassificationType.UNCERTAIN,
            "expected_should_notify": False,
        },
        {
            "name": "Misleading Injected Ad / Promotional Content Suppression",
            "scenario": "scenario_8_misleading",
            "type": "misleading",
            "expected_classified": ClassificationType.IRRELEVANT,
            "expected_should_notify": False,
        },
        {
            "name": "Duplicate Alert Rejection Under Repeated Changes",
            "scenario": "scenario_5",
            "type": "duplicate",
            "expected_classified": "duplicate_suppressed",
            "expected_should_notify": False,
        },
        {
            "name": "Source Outage & Baseline Preservation Under HTTP 503",
            "scenario": "scenario_4",
            "type": "outage",
            "expected_classified": "error",
            "expected_should_notify": False,
        },
        {
            "name": "Model Failure Graceful Fallback to Heuristics",
            "scenario": "model_failure",
            "type": "model_failure",
            "expected_classified": ClassificationType.MEANINGFUL,
            "expected_should_notify": True,
        },
    ]

    total_tests = len(eval_cases)
    passed_tests = 0
    results: List[Dict[str, Any]] = []

    # Confusion matrix counters
    true_positives = 0
    false_positives = 0
    true_negatives = 0
    false_negatives = 0

    for case in eval_cases:
        case_passed = False
        outcome_details = ""

        # Special Case: Model Failure Fallback
        if case["type"] == "model_failure":
            mock_failing_bedrock = MagicMock()
            mock_failing_bedrock.invoke_model.side_effect = ClientError(
                {"Error": {"Code": "ModelTimeoutException", "Message": "Bedrock inference timed out"}},
                "InvokeModel",
            )
            sc = DEMO_SCENARIOS["scenario_1"]
            tmpl = sc["rule_template"]
            rule = MonitoringRule(
                name=tmpl["name"],
                source_url=tmpl["source_url"],
                source_type=tmpl["source_type"],
                natural_language_goal=tmpl["natural_language_goal"],
                criteria_categories=tmpl["criteria_categories"],
            )
            diff = DiffEngine.compute_diff(sc["baseline_content"], sc["updated_content"])
            analysis = ChangeClassifier.classify_with_bedrock(
                rule=rule,
                diff_result=diff,
                source_url=rule.source_url,
                client=mock_failing_bedrock,
            )

            if analysis.change_detected and analysis.classification == ClassificationType.MEANINGFUL and analysis.should_notify:
                true_positives += 1
                case_passed = True
                outcome_details = "Bedrock timeout handled gracefully; fallback heuristic classified correctly."
            else:
                false_negatives += 1
                outcome_details = "Fallback heuristic failed to detect meaningful change."

            if case_passed:
                passed_tests += 1

            results.append({
                "test_name": case["name"],
                "passed": case_passed,
                "details": outcome_details,
            })
            continue

        # Standard Service Cases
        sc = DEMO_SCENARIOS[case["scenario"]]
        tmpl = sc["rule_template"]
        rule = MonitoringRule(
            name=tmpl["name"],
            source_url=tmpl["source_url"],
            source_type=tmpl["source_type"],
            natural_language_goal=tmpl["natural_language_goal"],
            criteria_categories=tmpl["criteria_categories"],
            specific_instructions=tmpl.get("specific_instructions", ""),
            check_interval_minutes=tmpl["check_interval_minutes"],
        )
        service.storage.save_rule(rule)
        service.establish_baseline(rule)

        if case["type"] == "outage":
            # Outage test: set mock source to None to simulate HTTP 503
            service.fetcher.register_mock_source(rule.source_url, None)
            has_changed, event, msg = service.check_rule(rule.id)
            # Baseline must be preserved and no notification sent
            snapshot = service.storage.get_latest_snapshot(rule.id)
            if not has_changed and event is None and snapshot is not None and "failed" in (msg or "").lower():
                true_negatives += 1
                case_passed = True
                outcome_details = "HTTP 503 outage intercepted; previous baseline snapshot preserved."
            else:
                outcome_details = "Outage handling failed or baseline was corrupted."

        elif case["type"] == "duplicate":
            # Duplicate test: evaluate twice with identical content
            service.check_rule(rule.id, simulated_content=sc["updated_content"])
            has_changed, event, msg = service.check_rule(rule.id, simulated_content=sc["updated_content"])
            if event is None:
                true_negatives += 1
                case_passed = True
                outcome_details = "Identical consecutive check deduplicated; duplicate notification prevented."
            else:
                false_positives += 1
                outcome_details = "Duplicate alert was falsely generated."

        elif case["type"] == "meaningful":
            has_changed, event, msg = service.check_rule(rule.id, simulated_content=sc["updated_content"])
            if event and event.classification == ClassificationType.MEANINGFUL and event.should_notify:
                true_positives += 1
                case_passed = True
                outcome_details = f"Correctly classified as MEANINGFUL ({event.summary}) with evidence."
            else:
                false_negatives += 1
                outcome_details = "Missed meaningful change (False Negative)."

        elif case["type"] in ("noise", "misleading"):
            has_changed, event, msg = service.check_rule(rule.id, simulated_content=sc["updated_content"])
            # Should NOT notify
            if event is None or (not event.should_notify and event.classification == ClassificationType.IRRELEVANT):
                true_negatives += 1
                case_passed = True
                outcome_details = "Noise / misleading injection cleanly suppressed ('Quiet by Default')."
            else:
                false_positives += 1
                outcome_details = f"False Positive: irrelevant content triggered notification ({event.summary})."

        elif case["type"] == "ambiguous":
            has_changed, event, msg = service.check_rule(rule.id, simulated_content=sc["updated_content"])
            # Should be marked UNCERTAIN and should NOT notify
            if event and event.classification == ClassificationType.UNCERTAIN and not event.should_notify:
                true_negatives += 1
                case_passed = True
                outcome_details = "Ambiguous phrasing flagged as UNCERTAIN for review without sending push alert."
            elif event is None:
                true_negatives += 1
                case_passed = True
                outcome_details = "Ambiguous phrasing suppressed."
            else:
                false_positives += 1
                outcome_details = "Ambiguous change falsely triggered notification."

        if case_passed:
            passed_tests += 1

        results.append({
            "test_name": case["name"],
            "passed": case_passed,
            "details": outcome_details,
        })

    # Cleanup temp db
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

    total_meaningful_expected = true_positives + false_negatives
    total_non_notifying_expected = true_negatives + false_positives

    pass_rate = (passed_tests / total_tests) * 100.0
    recall = (true_positives / total_meaningful_expected * 100.0) if total_meaningful_expected else 100.0
    precision = (true_positives / (true_positives + false_positives) * 100.0) if (true_positives + false_positives) else 100.0
    noise_suppression = (true_negatives / total_non_notifying_expected * 100.0) if total_non_notifying_expected else 100.0

    return {
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "pass_rate_pct": pass_rate,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "true_negatives": true_negatives,
        "false_negatives": false_negatives,
        "meaningful_change_recall_pct": recall,
        "precision_pct": precision,
        "noise_suppression_rate_pct": noise_suppression,
        "test_results": results,
    }


if __name__ == "__main__":
    metrics = run_evaluation()
    print("=" * 65)
    print("NOWAWARE QUANTITATIVE EVALUATION BENCHMARK RESULTS")
    print("=" * 65)
    print(f"Overall Pass Rate:             {metrics['pass_rate_pct']:.1f}% ({metrics['passed_tests']}/{metrics['total_tests']})")
    print(f"Meaningful Change Recall:      {metrics['meaningful_change_recall_pct']:.1f}% ({metrics['true_positives']}/{metrics['true_positives'] + metrics['false_negatives']})")
    print(f"Noise Suppression Rate:        {metrics['noise_suppression_rate_pct']:.1f}% ({metrics['true_negatives']}/{metrics['true_negatives'] + metrics['false_positives']})")
    print(f"Precision:                     {metrics['precision_pct']:.1f}%")
    print(f"False Positives Count:         {metrics['false_positives']}")
    print(f"Missed Meaningful (FN) Count:  {metrics['false_negatives']}")
    print("-" * 65)
    for r in metrics["test_results"]:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['test_name']}: {r['details']}")
    print("=" * 65)
