"""Fail-closed contracts for project-local release dependencies."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable


class DependencyContractError(ValueError):
    """Raised when a frozen dependency differs from its reviewed identity."""


@dataclass(frozen=True)
class CSVSpec:
    """Locked identity and structure for one portable release input."""

    fields: tuple[str, ...]
    rows: int
    unique_key: tuple[str, ...]
    sha256: str
    derivation: str


POULTRY = ("鸡", "火鸡", "鸭", "鹅")
ANIMAL_LEAVES = (
    "牛",
    "羊",
    "猪",
    "马",
    "兔",
    "鹿",
    "鸡",
    "火鸡",
    "鸭",
    "鹅",
    "鱼",
    "虾",
    "蜜蜂",
)


def animal_members(label: str) -> set[str]:
    """Expand a target-animal label to covered leaf animals."""

    output: set[str] = set()
    for token in (token for token in label.split("/") if token):
        if token == "所有食品动物":
            output.update(ANIMAL_LEAVES)
        elif token in {"家禽", "禽"}:
            output.update(POULTRY)
        elif token == "其他动物":
            continue
        elif token in {"绵羊", "山羊"}:
            output.add("羊")
        else:
            output.add(token)
    return output


POLLUTANT_FIELDS = (
    "year",
    "analyte",
    "food_category",
    "limit_value",
    "unit",
    "confidence",
    "note",
)

RELEASE_DEPENDENCY_SPECS: dict[str, CSVSpec] = {
    "food_taxonomy.csv": CSVSpec(
        fields=("child", "parent", "level", "src_year"),
        rows=798,
        unique_key=("child", "parent", "src_year"),
        sha256="f5730ffcc4bfe4f54a427445a2a392fbdb473de609a6aa3b23584f6ced415f7d",
        derivation="parser_derived_from_normative_appendix_a",
    ),
    "category_alias.csv": CSVSpec(
        fields=("异名", "规范名", "status", "说明"),
        rows=10,
        unique_key=("异名",),
        sha256="3137a085f1c25e73c4d2962fd6c8d787b80159d56d4d3474c109d741af6f531f",
        derivation="human_adjudication_seed",
    ),
    "category_containment.csv": CSVSpec(
        fields=("成员", "上级", "status", "说明"),
        rows=7,
        unique_key=("成员",),
        sha256="9f94d87716553d3bc119e3605e5d757153ba54b1c1d401853e4fe302c32d1346",
        derivation="human_adjudication_seed",
    ),
    "pollutant_old_path.csv": CSVSpec(
        fields=POLLUTANT_FIELDS,
        rows=677,
        unique_key=("year", "analyte", "food_category"),
        sha256="e05158cd82b8f5dc7cd0cb7c5a770e88c18fefa5e3d9d9593a3f142fbaa83c8f",
        derivation="legacy_text_parser_plus_coordinate_double_column_rows",
    ),
    "pollutant_doublecol_long.csv": CSVSpec(
        fields=POLLUTANT_FIELDS,
        rows=241,
        unique_key=("year", "analyte", "food_category"),
        sha256="e0955c56f5d3a048a1fb38b49c6cb7a750b4cd475fe9d68012a463b540fd1345",
        derivation="frozen_coordinate_parser_sidecar",
    ),
    "member_crosswalk_mycotoxin.csv": CSVSpec(
        fields=(
            "toxin",
            "member",
            "v2005",
            "v2011",
            "v2017",
            "unit",
            "trend",
            "类别重组",
            "归属2005",
            "归属2011",
            "归属2017",
        ),
        rows=55,
        unique_key=("toxin", "member"),
        sha256="04fcaf11730263facb7e6be652fc51d7a2f121ce8a1c8f4f9b87ddee61967626",
        derivation="deterministic_member_expansion",
    ),
    "member_crosswalk_vetdrug.csv": CSVSpec(
        fields=(
            "drug",
            "english",
            "animal",
            "tissue",
            "v2002",
            "v2019",
            "v2022",
            "unit",
            "trend",
            "归属2002",
            "归属2019",
            "归属2022",
        ),
        rows=1157,
        unique_key=("drug", "animal", "tissue"),
        sha256="02e8ee1e47c5d786cc51b544ae730096e32c0a67646bc76bffc3b4052420402e",
        derivation="deterministic_member_expansion",
    ),
}


def sha256_file(path: str | Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_locked_csv(path: str | Path, spec: CSVSpec) -> list[dict[str, str]]:
    """Read a frozen CSV after identity, schema, row, and key checks."""

    path = Path(path)
    if not path.is_file():
        raise DependencyContractError(
            f"required portable input is missing: {path}"
        )
    digest = sha256_file(path)
    if digest != spec.sha256:
        raise DependencyContractError(
            f"portable input digest differs for {path.name}: "
            f"expected {spec.sha256}, got {digest}"
        )
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != spec.fields:
            raise DependencyContractError(
                f"unexpected schema for {path.name}: {reader.fieldnames}"
            )
        rows = list(reader)
    if len(rows) != spec.rows:
        raise DependencyContractError(
            f"unexpected row count for {path.name}: "
            f"expected {spec.rows}, got {len(rows)}"
        )
    keys = [tuple(row[field] for field in spec.unique_key) for row in rows]
    if any(not all(key) for key in keys):
        raise DependencyContractError(
            f"blank business-key component in {path.name}"
        )
    if len(keys) != len(set(keys)):
        raise DependencyContractError(f"duplicate business key in {path.name}")
    return rows


def read_release_dependency(
    input_dir: str | Path, filename: str
) -> list[dict[str, str]]:
    """Read one named release dependency through its locked contract."""

    if filename not in RELEASE_DEPENDENCY_SPECS:
        raise DependencyContractError(
            f"no locked release-dependency contract for {filename}"
        )
    return read_locked_csv(
        Path(input_dir) / filename, RELEASE_DEPENDENCY_SPECS[filename]
    )


def verify_release_dependencies(
    input_dir: str | Path,
    filenames: Iterable[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Verify a selected set, or the complete frozen dependency bundle."""

    selected = tuple(filenames or RELEASE_DEPENDENCY_SPECS)
    loaded = {
        filename: read_release_dependency(input_dir, filename)
        for filename in selected
    }
    if "category_alias.csv" in loaded:
        statuses = [row["status"] for row in loaded["category_alias.csv"]]
        if statuses.count("已确认") != 5 or statuses.count("待核") != 5:
            raise DependencyContractError(
                "category alias adjudication counts differ from 5 confirmed and 5 pending"
            )
    if "category_containment.csv" in loaded:
        statuses = [row["status"] for row in loaded["category_containment.csv"]]
        if statuses.count("已确认") != 7 or len(statuses) != 7:
            raise DependencyContractError(
                "category containment adjudications differ from 7 confirmed"
            )
    return loaded


POLLUTANT_REBUILD_DEPENDENCIES = (
    "pollutant_old_path.csv",
    "food_taxonomy.csv",
    "category_alias.csv",
    "category_containment.csv",
)
POLLUTANT_RELEASE_OUTPUTS = (
    "pollutant_limits_by_version.csv",
    "category_crosswalk.csv",
    "member_crosswalk.csv",
    "pollutant_quarantine.csv",
)
REVIEWED_ALIAS_AUDIT = {
    "confirmed_applied": 5,
    "pending_review_excluded": 5,
    "pending_review_sources": [
        "麦片、面筋、粥类罐头、带馅面米制品",
        "肉及肉制品",
        "畜禽肝脏及其制品",
        "畜禽肾脏及其制品",
        "谷物碾磨加工品除外]",
    ],
}


def verify_pollutant_rebuild_report(
    interim_dir: str | Path, dependency_dir: str | Path
) -> dict[str, object]:
    """Reject stale pollutant outputs before they enter the formal release."""

    verify_release_dependencies(dependency_dir, POLLUTANT_REBUILD_DEPENDENCIES)
    interim_dir = Path(interim_dir)
    report_path = interim_dir / "pollutant_rebuild_report.json"
    if not report_path.is_file():
        raise DependencyContractError(
            f"required pollutant rebuild report is missing: {report_path}"
        )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise DependencyContractError(
            f"invalid pollutant rebuild report: {report_path}"
        ) from error

    report_inputs = report.get("inputs")
    report_outputs = report.get("outputs")
    alias_audit = report.get("alias_adjudications")
    if not isinstance(report_inputs, dict) or not isinstance(report_outputs, dict):
        raise DependencyContractError(
            "pollutant rebuild report lacks input or output digests"
        )
    if alias_audit != REVIEWED_ALIAS_AUDIT:
        raise DependencyContractError(
            "pollutant rebuild report lacks the reviewed alias exclusion audit"
        )

    for filename in POLLUTANT_REBUILD_DEPENDENCIES:
        expected = RELEASE_DEPENDENCY_SPECS[filename].sha256
        if report_inputs.get(filename) != expected:
            raise DependencyContractError(
                f"pollutant rebuild used a different dependency: {filename}"
            )
    for filename in POLLUTANT_RELEASE_OUTPUTS:
        path = interim_dir / filename
        if not path.is_file():
            raise DependencyContractError(
                f"required pollutant rebuild output is missing: {path}"
            )
        observed = sha256_file(path)
        if report_outputs.get(filename) != observed:
            raise DependencyContractError(
                f"pollutant rebuild output differs from its report: {filename}"
            )
    return report
