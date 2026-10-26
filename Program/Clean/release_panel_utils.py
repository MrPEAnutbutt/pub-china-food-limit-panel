"""Build conservative, provenance-preserving release panels from long records."""

import json
import hashlib
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from decimal import InvalidOperation

from release_dependency_utils import animal_members


PESTICIDE_YEARS = ("2012", "2014", "2016", "2019", "2021", "2026")
ADDITIVE_YEARS = ("2011", "2014", "2024")
VETDRUG_SUMMARY_YEARS = ("2002", "2019")

PESTICIDE_V2_RULE_COLUMNS = (
    "record_id",
    "version_year",
    "limit_value",
    "unit",
    "pesticide_key",
    "pesticide_zh",
    "pesticide_en",
    "pesticide_zh_raw",
    "pesticide_en_raw",
    "parent_category_zh",
    "parent_category_raw",
    "food_key",
    "food_zh",
    "food_raw",
    "limit_qualifier",
    "is_temporary",
    "value_raw",
    "review_status",
    "edition_source_id",
    "extraction_source_id",
    "source_copy_role",
    "source_page",
    "source_y",
    "food_x",
    "parent_assignment_method",
    "table_open_method",
)

PESTICIDE_V2_SCOPE_COLUMNS = (
    "pesticide_zh_raw",
    "parent_category_zh",
    "food_raw",
    "limit_qualifier",
    "is_temporary",
)

ENTITY_ID_PREFIXES = {
    "pesticide": "PST",
    "food": "FOD",
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sorted_unique(values):
    unique = {str(value) for value in values if value not in (None, "")}

    def sort_key(value):
        number = _number(value)
        return (number is None, number if number is not None else value)

    return sorted(unique, key=sort_key)


def _normalise_codes(value):
    return ",".join(sorted(part.strip() for part in value.split(",") if part.strip()))


def _edition_gap(present_years, years):
    """True when the compared editions skip an edition in between."""
    positions = [years.index(year) for year in present_years]
    return positions != list(range(positions[0], positions[-1] + 1))


def _covered_animals(labels):
    animals = set()
    for label in labels:
        animals |= animal_members(label)
        if "其他动物" in label.split("/"):
            animals.add("其他动物")
    return animals


def _normalise_vetdrug_english(value):
    """Return the punctuation-insensitive identity used by the vet summary."""
    identity = re.sub(r"[^0-9a-z]+", "", str(value or "").casefold())
    if not identity:
        raise ValueError("veterinary-drug row has an empty English identity")
    return identity


def _decimal_text(value):
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def build_vetdrug_summary_panel(long_rows):
    """Build the 2002/2019 drug-tissue summary directly from released rules.

    GB 31650.1--2022 rules remain in the long table and in the separately
    supplied member interface.  They do not enter this two-edition summary.
    Grouping only the two represented editions prevents a 2022-only rule from
    becoming an empty, falsely labelled summary row.
    """
    grouped = defaultdict(lambda: defaultdict(set))
    animals = defaultdict(lambda: defaultdict(set))
    display_rows = defaultdict(list)
    year_rank = {year: index for index, year in enumerate(VETDRUG_SUMMARY_YEARS)}

    for source_row in long_rows:
        row = dict(source_row)
        year = str(row.get("version_year", "") or "").strip()
        if year == "2022":
            continue
        if year not in VETDRUG_SUMMARY_YEARS:
            raise ValueError(f"unsupported veterinary-drug version_year: {year}")
        drug_zh = str(row.get("drug_zh", "") or "").strip()
        tissue = str(row.get("tissue_zh", "") or "").strip()
        if not drug_zh or not tissue:
            raise ValueError("veterinary-drug summary requires drug and tissue labels")
        identity = _normalise_vetdrug_english(row.get("drug_en", ""))
        try:
            value = Decimal(str(row.get("limit_value", "") or "").strip())
        except InvalidOperation as error:
            raise ValueError(
                "non-numeric veterinary-drug limit: "
                f"{row.get('limit_value', '')}"
            ) from error
        if not value.is_finite():
            raise ValueError(
                "non-numeric veterinary-drug limit: "
                f"{row.get('limit_value', '')}"
            )
        key = (identity, tissue)
        grouped[key][year].add(value)
        animals[key][year].add(str(row.get("animal", "") or ""))
        display_rows[key].append(row)

    output = []
    for identity, tissue in sorted(grouped):
        year_values = grouped[(identity, tissue)]
        values_2002 = sorted(year_values.get("2002", set()))
        values_2019 = sorted(year_values.get("2019", set()))
        if not values_2002 and not values_2019:
            raise RuntimeError("veterinary-drug summary group has no represented rule")
        if values_2002 and not values_2019:
            trend = "single_2002_unmatched"
        elif values_2019 and not values_2002:
            trend = "single_2019_unmatched"
        elif len(values_2002) != 1 or len(values_2019) != 1:
            trend = "unresolved_multiple_animals"
        elif _covered_animals(animals[(identity, tissue)]["2002"]) != _covered_animals(
            animals[(identity, tissue)]["2019"]
        ):
            # The same value then applies to a different set of animals.
            trend = "incomparable_scope_text"
        elif values_2002[0] == values_2019[0]:
            trend = "stable"
        elif values_2019[0] < values_2002[0]:
            trend = "tightened"
        else:
            trend = "relaxed"
        display = max(
            display_rows[(identity, tissue)],
            key=lambda row: (
                year_rank[str(row["version_year"])],
                str(row.get("record_id", "") or ""),
            ),
        )
        output.append(
            {
                "standard": "GB 31650",
                "drug_zh": display["drug_zh"],
                "drug_en": identity,
                "tissue_zh": tissue,
                "v2002": "/".join(_decimal_text(value) for value in values_2002),
                "v2019": "/".join(_decimal_text(value) for value in values_2019),
                "unit": "μg/kg",
                "trend": trend,
            }
        )
    return output


def _normalise_scope_text(value):
    """Normalise typography while retaining scope-bearing words and symbols."""
    text = unicodedata.normalize("NFKC", value or "")
    text = re.sub(r"\s+", "", text)
    text = (
        text.replace("≦", "≤")
        .replace("⩽", "≤")
        .replace("≧", "≥")
        .replace("⩾", "≥")
    )
    text = re.sub(r"[,、;:。]", "", text)
    return re.sub(r"(?<!\d)\.|\.(?!\d)", "", text)


def _cell(records, value_column, rule_columns):
    if not records:
        return {
            "status": "missing",
            "value": "",
            "values": [],
            "units": [],
            "record_ids": [],
            "rules": [],
            "candidate_count": 0,
            "distinct_value_count": 0,
        }

    records = sorted(records, key=lambda row: row["record_id"])
    values = _sorted_unique(row.get(value_column, "") for row in records)
    units = _sorted_unique(row.get("unit", "") for row in records)
    if len(records) == 1:
        status = "single"
        value = records[0].get(value_column, "")
    elif len(values) > 1 or len(units) > 1:
        status = "multiple_distinct_values"
        value = ""
    else:
        status = "multiple_same_value"
        value = ""

    rules = [
        {column: row.get(column, "") for column in rule_columns}
        for row in records
    ]
    return {
        "status": status,
        "value": value,
        "values": values,
        "units": units,
        "record_ids": [row["record_id"] for row in records],
        "rules": rules,
        "candidate_count": len(records),
        "distinct_value_count": len(values),
    }


def _trend(cells, years, scope_columns=()):
    present = [cells[year] for year in years if cells[year]["status"] != "missing"]
    if not present:
        return "no_records"
    if any(cell["status"] != "single" for cell in present):
        return "incomparable_multiple_rules"
    if len(present) == 1:
        return "single_version"

    units = {cell["units"][0] if cell["units"] else "" for cell in present}
    if len(units) > 1:
        return "incomparable_units"

    if scope_columns:
        scope_signatures = {
            tuple(
                _normalise_scope_text(cell["rules"][0].get(column, ""))
                for column in scope_columns
            )
            for cell in present
        }
        if len(scope_signatures) > 1:
            return "incomparable_scope_text"

    present_years = [year for year in years if cells[year]["status"] != "missing"]
    if _edition_gap(present_years, years):
        return "incomparable_edition_gap"

    values = [cell["value"] for cell in present]
    if all(value == "GMP" for value in values):
        return "stable_gmp"
    numbers = [_number(value) for value in values]
    if any(number is None for number in numbers):
        return "incomparable_non_numeric"
    if len(set(numbers)) == 1:
        return "stable"
    nonincreasing = all(left >= right for left, right in zip(numbers, numbers[1:]))
    nondecreasing = all(left <= right for left, right in zip(numbers, numbers[1:]))
    if nonincreasing and numbers[-1] < numbers[0]:
        return "tightened"
    if nondecreasing and numbers[-1] > numbers[0]:
        return "relaxed"
    return "fluctuation"


def _cell_columns(row, cells, years):
    for year in years:
        cell = cells[year]
        row[f"v{year}"] = cell["value"]
        row[f"status_{year}"] = cell["status"]
        row[f"values_{year}"] = _json(cell["values"])
        row[f"units_{year}"] = _json(cell["units"])
        row[f"source_record_ids_{year}"] = _json(cell["record_ids"])
        row[f"rules_{year}"] = _json(cell["rules"])
        row[f"candidate_count_{year}"] = cell["candidate_count"]
        row[f"distinct_value_count_{year}"] = cell["distinct_value_count"]


def panel_columns(base_columns, years, tail_columns):
    columns = list(base_columns)
    columns.extend(f"v{year}" for year in years)
    for prefix in (
        "status",
        "values",
        "units",
        "source_record_ids",
        "rules",
        "candidate_count",
        "distinct_value_count",
    ):
        columns.extend(f"{prefix}_{year}" for year in years)
    columns.extend(tail_columns)
    return columns


def _normalise_pesticide_scope_text(value):
    """Canonicalise typography without erasing pesticide rule scope."""
    text = unicodedata.normalize(
        "NFKC", str(value if value is not None else "")
    )
    text = text.translate(
        str.maketrans(
            {
                "、": ",",
                "，": ",",
                "﹐": ",",
                "；": ";",
                "﹔": ";",
                "：": ":",
                "﹕": ":",
                "。": ".",
                "．": ".",
                "﹒": ".",
                "‐": "-",
                "‑": "-",
                "‒": "-",
                "–": "-",
                "—": "-",
                "−": "-",
                "≦": "≤",
                "⩽": "≤",
                "≧": "≥",
                "⩾": "≥",
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
                "【": "[",
                "】": "]",
                "·": "·",
                "•": "·",
                "‧": "·",
            }
        )
    )
    text = re.sub(r"[\s\u200b\u200c\u200d\ufeff]+", "", text)
    text = text.replace('"', "").replace("'", "")

    kept = []
    for index, character in enumerate(text):
        previous = text[index - 1] if index else ""
        following = text[index + 1] if index + 1 < len(text) else ""
        between_digits = previous.isdigit() and following.isdigit()
        if character in {",", ";"}:
            if between_digits:
                kept.append(",")
            continue
        if character == ":":
            if between_digits:
                kept.append(character)
            continue
        if character == ".":
            if between_digits:
                kept.append(character)
            continue
        kept.append(character)
    return "".join(kept)


def _stable_entity_id(entity_type, canonical_key):
    """Return a deterministic ASCII identifier without exposing private paths."""
    if entity_type not in ENTITY_ID_PREFIXES:
        raise ValueError(f"unsupported entity type: {entity_type}")
    if not canonical_key:
        raise ValueError(f"empty canonical key for {entity_type}")
    digest = hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()[:16]
    return f"{ENTITY_ID_PREFIXES[entity_type]}-{digest}"


def pesticide_entity_key(pesticide_en, pesticide_zh):
    """Create a cross-edition key from the printed common name.

    Every released GB 2763 section carries an English common name.  Chinese is
    retained as an explicit fallback so that malformed inputs fail locally
    rather than losing a rule.  Typographic spacing is ignored; chemical-form
    punctuation and digits remain part of the key.
    """
    english = _normalise_pesticide_scope_text(pesticide_en).casefold()
    if english:
        return f"en:{english}"
    chinese = _normalise_pesticide_scope_text(pesticide_zh).casefold()
    if chinese:
        return f"zh:{chinese}"
    raise ValueError("pesticide entity requires an English or Chinese name")


def food_entity_key(food_zh):
    """Create a conservative base-food key while retaining scope in the rule.

    Parenthetical qualifiers are omitted from the grouping key so that variants
    such as ``fresh``, ``dried``, ``except``, or ``only`` remain together.  The
    original food text stays in each rule and the trend gate then marks differing
    scopes as incomparable.  This prevents a qualified value from being treated
    as an unrestricted value.
    """
    full = _normalise_pesticide_scope_text(food_zh).casefold()
    if not full:
        raise ValueError("food entity requires a Chinese label")
    base = full
    previous = None
    while base != previous:
        previous = base
        base = re.sub(r"\([^()]*\)|\[[^\[\]]*\]", "", base)
    base = base.strip("-_/.,;:")
    return f"zh:{base or full}"


def pesticide_entity_id(pesticide_en, pesticide_zh):
    return _stable_entity_id(
        "pesticide", pesticide_entity_key(pesticide_en, pesticide_zh)
    )


def food_entity_id(food_zh):
    return _stable_entity_id("food", food_entity_key(food_zh))


def _normalise_temporary_flag(value):
    text = _normalise_pesticide_scope_text(value).casefold()
    if text in {"", "0", "false", "no", "n", "否"}:
        return "0"
    if text in {"1", "true", "yes", "y", "是"}:
        return "1"
    return text


def _pesticide_v2_scope_signature(rule):
    signature = []
    for column in PESTICIDE_V2_SCOPE_COLUMNS:
        value = rule.get(column, "")
        if column == "is_temporary":
            signature.append(_normalise_temporary_flag(value))
        else:
            signature.append(_normalise_pesticide_scope_text(value).casefold())
    return tuple(signature)


def _pesticide_v2_has_unresolved_scope(rule):
    raw_review_status = unicodedata.normalize(
        "NFKC", str(rule.get("review_status", "") or "")
    ).casefold()
    review_status = _normalise_pesticide_scope_text(raw_review_status).casefold()
    qualifier = _normalise_pesticide_scope_text(
        rule.get("limit_qualifier", "")
    ).casefold()
    unresolved_words = (
        "unresolved",
        "uncertain",
        "ambiguous",
        "pending",
        "quarantin",
        "待核",
        "需核",
        "需复核",
        "不可靠",
        "存疑",
    )
    if any(word in review_status or word in qualifier for word in unresolved_words):
        return True
    if re.fullmatch(r"[*∗]?[a-z]", qualifier, flags=re.IGNORECASE):
        return True
    return bool(re.search(r"(?:^|[;,|])\s*review_", raw_review_status))


def _pesticide_v2_decimal(value):
    text = unicodedata.normalize(
        "NFKC", str(value if value is not None else "")
    ).strip()
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _pesticide_v2_unit(value):
    return _normalise_pesticide_scope_text(value).casefold()


def _pesticide_v2_cell(records):
    if not records:
        return {
            "status": "missing",
            "value": "",
            "values": [],
            "units": [],
            "record_ids": [],
            "source_ids": [],
            "edition_source_ids": [],
            "extraction_source_ids": [],
            "rules": [],
            "candidate_count": 0,
            "distinct_value_count": 0,
        }

    records = sorted(records, key=lambda row: row["record_id"])
    rules = [
        {column: record.get(column, "") for column in PESTICIDE_V2_RULE_COLUMNS}
        for record in records
    ]
    values = _sorted_unique(record.get("limit_value", "") for record in records)
    units = _sorted_unique(record.get("unit", "") for record in records)
    if len(records) == 1:
        status = "single_rule"
        value = records[0].get("limit_value", "")
    elif len(values) <= 1:
        status = "multiple_rules_same_value"
        value = ""
    else:
        status = "multiple_rules_distinct_values"
        value = ""

    source_ids = []
    for record in records:
        source_ids.extend(
            record.get(column, "")
            for column in (
                "source_id",
                "edition_source_id",
                "extraction_source_id",
            )
        )
    return {
        "status": status,
        "value": value,
        "values": values,
        "units": units,
        "record_ids": [record["record_id"] for record in records],
        "source_ids": _sorted_unique(source_ids),
        "edition_source_ids": _sorted_unique(
            record.get("edition_source_id", "") for record in records
        ),
        "extraction_source_ids": _sorted_unique(
            record.get("extraction_source_id", "") for record in records
        ),
        "rules": rules,
        "candidate_count": len(records),
        "distinct_value_count": len(values),
    }


def _pesticide_v2_trend(cells):
    present = [
        cells[year]
        for year in PESTICIDE_YEARS
        if cells[year]["status"] != "missing"
    ]
    if any(cell["candidate_count"] > 1 for cell in present):
        return "incomparable_multiple_rules"
    if len(present) == 1:
        return "single_version"

    units = {
        _pesticide_v2_unit(cell["rules"][0].get("unit", ""))
        for cell in present
    }
    if len(units) > 1:
        return "incomparable_units"

    if any(
        _pesticide_v2_has_unresolved_scope(cell["rules"][0]) for cell in present
    ):
        return "incomparable_unresolved_review_or_source_qualifier"

    scopes = {
        _pesticide_v2_scope_signature(cell["rules"][0]) for cell in present
    }
    if len(scopes) > 1:
        return "incomparable_scope_text"

    present_years = [
        year for year in PESTICIDE_YEARS if cells[year]["status"] != "missing"
    ]
    if _edition_gap(present_years, PESTICIDE_YEARS):
        return "incomparable_edition_gap"

    numbers = [_pesticide_v2_decimal(cell["value"]) for cell in present]
    if any(number is None for number in numbers):
        return "incomparable_non_numeric"
    if len(set(numbers)) == 1:
        return "stable"
    nonincreasing = all(left >= right for left, right in zip(numbers, numbers[1:]))
    nondecreasing = all(left <= right for left, right in zip(numbers, numbers[1:]))
    if nonincreasing and numbers[-1] < numbers[0]:
        return "tightened"
    if nondecreasing and numbers[-1] > numbers[0]:
        return "relaxed"
    return "fluctuation"


def _pesticide_v2_cell_columns(row, cells):
    for year in PESTICIDE_YEARS:
        cell = cells[year]
        row[f"v{year}"] = cell["value"]
        row[f"status_{year}"] = cell["status"]
        for name in (
            "values",
            "units",
            "source_ids",
            "edition_source_ids",
            "extraction_source_ids",
            "rules",
        ):
            row[f"{name}_{year}"] = _json(cell[name])
        row[f"source_record_ids_{year}"] = _json(cell["record_ids"])
        row[f"candidate_count_{year}"] = cell["candidate_count"]
        row[f"distinct_value_count_{year}"] = cell["distinct_value_count"]


def _pesticide_v2_group_key(row):
    pesticide_key = str(row.get("pesticide_key", "") or "").strip()
    food_key = str(row.get("food_key", "") or "").strip()
    if pesticide_key and food_key:
        return pesticide_key, food_key

    pesticide_zh = str(row.get("pesticide_zh", "") or "").strip()
    food_zh = str(row.get("food_zh", "") or "").strip()
    if not pesticide_zh or not food_zh:
        raise ValueError(
            "pesticide panel v2 requires pesticide_key+food_key or "
            "pesticide_zh+food_zh"
        )
    return pesticide_zh, food_zh


def build_pesticide_panel_v2(long_rows):
    """Build a rule-preserving pesticide panel with conservative trend gates."""
    grouped = defaultdict(lambda: defaultdict(list))
    record_ids = set()
    normalised_rows = []
    for source_row in long_rows:
        row = dict(source_row)
        record_id = str(row.get("record_id", "") or "").strip()
        if not record_id:
            raise ValueError("pesticide panel v2 requires a non-empty record_id")
        if record_id in record_ids:
            raise ValueError(f"duplicate pesticide record_id: {record_id}")
        record_ids.add(record_id)
        row["record_id"] = record_id
        year = str(row.get("version_year", "") or "").strip()
        if year not in PESTICIDE_YEARS:
            raise ValueError(f"unsupported pesticide version_year: {year}")
        row["version_year"] = year
        key = _pesticide_v2_group_key(row)
        grouped[key][year].append(row)
        normalised_rows.append(row)

    out = []
    referenced_ids = []
    year_rank = {year: index for index, year in enumerate(PESTICIDE_YEARS)}
    for pesticide_key, food_key in sorted(grouped):
        records = grouped[(pesticide_key, food_key)]
        cells = {
            year: _pesticide_v2_cell(records.get(year, []))
            for year in PESTICIDE_YEARS
        }
        all_records = [
            record
            for year in PESTICIDE_YEARS
            for record in records.get(year, [])
        ]
        display = max(
            all_records,
            key=lambda record: (
                year_rank[record["version_year"]],
                record["record_id"],
            ),
        )
        row = {
            "standard": "GB 2763",
            "pesticide_key": pesticide_key,
            "food_key": food_key,
            "pesticide_zh": display.get("pesticide_zh", ""),
            "food_zh": display.get("food_zh", ""),
            "pesticide_names_zh": _json(
                _sorted_unique(record.get("pesticide_zh", "") for record in all_records)
            ),
            "food_names_zh": _json(
                _sorted_unique(record.get("food_zh", "") for record in all_records)
            ),
        }
        _pesticide_v2_cell_columns(row, cells)
        row["n_versions"] = sum(
            cells[year]["status"] != "missing" for year in PESTICIDE_YEARS
        )
        row["trend"] = _pesticide_v2_trend(cells)
        out.append(row)
        for year in PESTICIDE_YEARS:
            referenced_ids.extend(cells[year]["record_ids"])

    if len(referenced_ids) != len(normalised_rows) or set(referenced_ids) != record_ids:
        raise RuntimeError("pesticide panel v2 did not conserve input record IDs")
    return out


def link_source_records(panel_rows, long_rows, years, cell_keys, long_key, unique=True):
    """Add `source_record_ids_<year>` once the panel record IDs are fixed.

    `cell_keys(row, year)` lists the long-table keys of the rules a cell
    reports, empty for an empty cell. With `unique` each key must name exactly
    one long row; otherwise at least one.
    """
    index = defaultdict(list)
    for row in long_rows:
        index[long_key(row)].append(row["record_id"])
    for row in panel_rows:
        for year in years:
            ids = []
            for key in cell_keys(row, year):
                matched = index.get(key, [])
                if not matched or (unique and len(matched) != 1):
                    raise ValueError(
                        f"{row['record_id']} {year}: {len(matched)} long rows for {key}"
                    )
                ids.extend(matched)
            row[f"source_record_ids_{year}"] = _json(sorted(ids))
    return panel_rows


def build_pesticide_panel(long_rows, metadata_rows):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in long_rows:
        key = (row["pesticide_zh"], row["food_zh"])
        grouped[key][row["version_year"]].append(row)

    metadata = {
        (row["农药_canon"], row["food_canon"]): row for row in metadata_rows
    }
    out = []
    rule_columns = (
        "record_id",
        "limit_value",
        "unit",
        "pesticide_raw",
        "food_raw",
        "source",
    )
    for pesticide, food in sorted(grouped):
        cells = {
            year: _cell(grouped[(pesticide, food)].get(year, []), "limit_value", rule_columns)
            for year in PESTICIDE_YEARS
        }
        meta = metadata.get((pesticide, food), {})
        trend = _trend(cells, PESTICIDE_YEARS)
        tier = meta.get("tier", "")
        if tier in {"待核(OCR异常)", "仅OCR(不可靠)"} and trend not in {
            "incomparable_multiple_rules",
            "incomparable_units",
        }:
            trend = "unresolved_ocr"
        row = {
            "standard": "GB 2763",
            "pesticide_zh": pesticide,
            "food_zh": food,
        }
        _cell_columns(row, cells, PESTICIDE_YEARS)
        present = [year for year in PESTICIDE_YEARS if cells[year]["status"] != "missing"]
        row.update(
            {
                "n_versions": len(present),
                "n_text_versions": sum(
                    any(rule.get("source") == "text" for rule in cells[year]["rules"])
                    for year in present
                ),
                "trend": trend,
                "ocr_flag": meta.get("ocr_flag", ""),
                "tier": "unresolved_multiple_rules"
                if trend == "incomparable_multiple_rules"
                else tier,
            }
        )
        out.append(row)
    return out


def build_additive_panel(long_rows):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in long_rows:
        cns = _normalise_codes(row["cns_code"])
        key = (cns, row["food_code"])
        grouped[key][row["version_year"]].append(row)

    out = []
    rule_columns = (
        "record_id",
        "additive_zh",
        "cns_code",
        "ins_code",
        "food_zh",
        "max_use",
        "unit",
        "note",
        "edition_source_id",
        "extraction_source_id",
    )
    for cns, food_code in sorted(grouped):
        records = grouped[(cns, food_code)]
        cells = {
            year: _cell(records.get(year, []), "max_use", rule_columns)
            for year in ADDITIVE_YEARS
        }
        all_records = [row for year in ADDITIVE_YEARS for row in records.get(year, [])]
        display = sorted(
            all_records,
            key=lambda row: (row["version_year"], row["record_id"]),
            reverse=True,
        )[0]
        row = {
            "standard": "GB 2760",
            "additive_zh": display["additive_zh"],
            "additive_names_zh": _json(_sorted_unique(r["additive_zh"] for r in all_records)),
            "cns_code": cns,
            "ins_codes": _json(_sorted_unique(r.get("ins_code", "") for r in all_records)),
            "food_code": food_code,
            "food_zh": display["food_zh"],
            "food_names_zh": _json(_sorted_unique(r["food_zh"] for r in all_records)),
        }
        _cell_columns(row, cells, ADDITIVE_YEARS)
        row["trend"] = _trend(
            cells,
            ADDITIVE_YEARS,
            scope_columns=("food_zh", "note"),
        )
        out.append(row)
    return out
