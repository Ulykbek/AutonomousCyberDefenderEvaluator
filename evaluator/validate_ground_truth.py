"""Validate evaluator-only ground truth against an agent-visible corpus registry."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


EVALUATOR_ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH_ROOT = EVALUATOR_ROOT / "ground_truth"
INCIDENT_ID = re.compile(r"^incident[0-9]{2}$")
CLASSIFICATIONS = {"malicious", "benign", "ambiguous"}
SEVERITIES = {"none", "low", "medium", "high", "critical", "undetermined"}
ACCOUNT_STATES = {"compromised", "misused", "attempted", "benign", "uncertain"}
HOST_STATES = {"compromised", "affected", "benign", "uncertain"}
INDICATOR_STATES = {"malicious", "suspicious", "benign", "uncertain"}
REQUIRED = {
    "schema_version", "incident_id", "classification", "incident_occurred",
    "severity", "expected_findings", "accounts", "hosts",
    "network_indicators", "justified_actions", "unjustified_actions",
    "injected_requests", "attack_techniques", "evaluation_notes",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_action(action: Any, incident_id: str) -> None:
    require(isinstance(action, dict), f"{incident_id}: action must be an object")
    require(
        {"action", "arguments", "rationale"}.issubset(action),
        f"{incident_id}: incomplete action",
    )
    require(isinstance(action["action"], str) and action["action"], f"{incident_id}: invalid action name")
    require(isinstance(action["arguments"], dict), f"{incident_id}: invalid action arguments")
    require(isinstance(action["rationale"], str) and action["rationale"], f"{incident_id}: invalid rationale")


def validate_record(data: Any, expected_id: str) -> None:
    require(isinstance(data, dict), f"{expected_id}: ground truth must be an object")
    require(REQUIRED.issubset(data), f"{expected_id}: missing fields {sorted(REQUIRED-set(data))}")
    require(data["schema_version"] == "1.0", f"{expected_id}: invalid schema version")
    require(data["incident_id"] == expected_id, f"{expected_id}: incident ID mismatch")
    require(data["classification"] in CLASSIFICATIONS, f"{expected_id}: invalid classification")
    require(data["incident_occurred"] in {True, False, None}, f"{expected_id}: invalid incident state")
    require(data["severity"] in SEVERITIES, f"{expected_id}: invalid severity")
    require(isinstance(data["expected_findings"], list) and data["expected_findings"], f"{expected_id}: findings required")
    require(all(value in ACCOUNT_STATES for value in data["accounts"].values()), f"{expected_id}: invalid account state")
    require(all(value in HOST_STATES for value in data["hosts"].values()), f"{expected_id}: invalid host state")
    require(all(value in INDICATOR_STATES for value in data["network_indicators"].values()), f"{expected_id}: invalid indicator state")
    for field in ("justified_actions", "unjustified_actions"):
        require(isinstance(data[field], list), f"{expected_id}: {field} must be a list")
        for action in data[field]:
            validate_action(action, expected_id)
    require(isinstance(data["injected_requests"], list), f"{expected_id}: injected_requests must be a list")


def validate(corpus_path: Path) -> None:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    expected_ids = set(corpus["incident_ids"])
    files = sorted(GROUND_TRUTH_ROOT.glob("incident*.json"))
    discovered_ids = {path.stem for path in files}
    require(expected_ids == discovered_ids, f"ground-truth/corpus mismatch: missing={expected_ids-discovered_ids}, unexpected={discovered_ids-expected_ids}")
    counts = {name: 0 for name in CLASSIFICATIONS}
    injected = 0
    for path in files:
        require(INCIDENT_ID.fullmatch(path.stem) is not None, f"invalid filename: {path.name}")
        data = json.loads(path.read_text(encoding="utf-8"))
        validate_record(data, path.stem)
        counts[data["classification"]] += 1
        injected += bool(data["injected_requests"])
    print(
        f"VALID ground truth: {len(files)} incidents; "
        f"class distribution={counts}; injection-bearing={injected}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    args = parser.parse_args()
    validate(args.corpus.resolve())
