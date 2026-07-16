import contextlib
import csv
import hashlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


CLEAN_DIR = Path(__file__).resolve().parents[1]
SCRIPT = CLEAN_DIR / "260715_food_category_en.py"
sys.path.insert(0, str(CLEAN_DIR))
SPEC = importlib.util.spec_from_file_location("food_category_en", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class FoodCategoryEnglishPortabilityTests(unittest.TestCase):
    def test_help_exposes_all_path_arguments(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--release-dir", result.stdout)
        self.assertIn("--translations-dir", result.stdout)
        self.assertIn("--report-output", result.stdout)

    def test_source_has_no_legacy_or_private_path_assumptions(self):
        source = SCRIPT.read_text(encoding="utf-8")

        for forbidden in ("03_Results", "04_Release", "/Users/", "/Volumes/"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn('r["source"]', source)

    def test_defaults_stay_inside_repository_workspace(self):
        args = MODULE.build_parser().parse_args([])

        for path in (args.release_dir, args.translations_dir, args.report_output):
            self.assertTrue(path.is_relative_to(MODULE.REPO_ROOT))

    def test_signature_match_keeps_unique_exact_match_and_rejects_tie(self):
        zh = [(f"P{i}", "食品甲", float(i)) for i in range(4)]
        en = [(f"P{i}", "Food A", float(i)) for i in range(4)]
        pairs, reasons, eligible_zh, eligible_en = MODULE.signature_match(zh, en)

        self.assertEqual(pairs, {"食品甲": "Food A"})
        self.assertEqual(reasons["食品甲"], ("exact_signature", 4))
        self.assertEqual((eligible_zh, eligible_en), (1, 1))

        tied_en = en + [(pesticide, "Food B", value) for pesticide, _, value in en]
        tied_pairs, _, _, _ = MODULE.signature_match(zh, tied_en)
        self.assertEqual(tied_pairs, {})

    def test_translation_pdf_digest_lock_fails_after_tampering(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            translations = Path(temporary_directory)
            pdf = translations / "translation.pdf"
            original = b"locked translation bytes"
            pdf.write_bytes(original)
            expected = {"translation.pdf": hashlib.sha256(original).hexdigest()}

            verified = MODULE.verify_translation_files(translations, expected=expected)
            self.assertEqual(verified["translation.pdf"], pdf)

            pdf.write_bytes(original + b" tampered")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                MODULE.verify_translation_files(translations, expected=expected)

    def test_main_rejects_tampered_pdf_before_parsing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            release = root / "release"
            translations = root / "translations"
            release.mkdir()
            translations.mkdir()
            (translations / "translation.pdf").write_bytes(b"tampered")
            expected = {"translation.pdf": hashlib.sha256(b"original").hexdigest()}

            with (
                mock.patch.object(MODULE, "TRANSLATION_PDFS", expected),
                mock.patch.object(MODULE, "raw") as parse_raw,
                self.assertRaisesRegex(ValueError, "SHA256 mismatch"),
            ):
                MODULE.main(
                    [
                        "--release-dir",
                        str(release),
                        "--translations-dir",
                        str(translations),
                        "--report-output",
                        str(root / "report.json"),
                    ]
                )
            parse_raw.assert_not_called()

    def test_pesticide_food_lookup_uses_stable_key_and_rejects_conflict(self):
        food_key = "FOD-0123456789abcdef"
        keyed, aliases, conflicts = MODULE.attach_pesticide_food_keys(
            {"食品甲": "Food A"},
            {"食品甲": ("exact_signature", 4)},
            [{"food_key": food_key, "food_zh": "食品甲"}],
        )

        self.assertEqual(keyed[food_key]["food_zh"], "食品甲")
        self.assertEqual(keyed[food_key]["food_en"], "Food A")
        self.assertEqual(aliases, {})
        self.assertEqual(conflicts, {})

        keyed, _, conflicts = MODULE.attach_pesticide_food_keys(
            {"食品甲": "Food A", "食品乙": "Food B"},
            {
                "食品甲": ("exact_signature", 4),
                "食品乙": ("exact_signature", 4),
            },
            [
                {"food_key": food_key, "food_zh": "食品甲"},
                {"food_key": food_key, "food_zh": "食品乙"},
            ],
        )
        self.assertNotIn(food_key, keyed)
        self.assertEqual(
            conflicts[food_key],
            ["食品乙 -> Food B", "食品甲 -> Food A"],
        )

    def test_main_accepts_v3_without_old_source_field(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            release = root / "release"
            translations = root / "translations"
            report = root / "reports" / "food_en_report.json"
            release.mkdir()
            translations.mkdir()

            write_csv(
                release / "additive_limits_long.csv",
                [
                    "food_code",
                    "food_zh",
                    "version_year",
                    "cns_code",
                    "max_use",
                    "additive_zh",
                ],
                [
                    {
                        "food_code": "01.0",
                        "food_zh": "乳制品",
                        "version_year": "2014",
                        "cns_code": "01.001",
                        "max_use": "1.0",
                        "additive_zh": "测试添加剂",
                    }
                ],
            )
            write_csv(
                release / "entity_names_en.csv",
                ["entity_key", "entity_type", "name_zh", "name_en"],
                [
                    {
                        "entity_key": f"PST-{i:016x}",
                        "entity_type": "pesticide",
                        "name_zh": f"不可用于连接{i}",
                        "name_en": f"P{i}",
                    }
                    for i in range(4)
                ],
            )
            food_key = "FOD-0123456789abcdef"
            pesticide_rows = [
                {
                    "version_year": "2016",
                    "pesticide_key": f"PST-{i:016x}",
                    "pesticide_zh": f"农药{i}",
                    "food_key": food_key,
                    "food_zh": "食品甲",
                    "limit_value": str(float(i)),
                }
                for i in range(4)
            ]
            write_csv(
                release / "pesticide_limits_long.csv",
                [
                    "version_year",
                    "pesticide_key",
                    "pesticide_zh",
                    "food_key",
                    "food_zh",
                    "limit_value",
                ],
                pesticide_rows,
            )
            write_csv(
                release / "pollutant_limits_long.csv",
                [
                    "version_year",
                    "analyte_en",
                    "analyte_zh",
                    "food_category_zh",
                    "limit_mgkg",
                    "limit_value",
                ],
                [
                    {
                        "version_year": "2022",
                        "analyte_en": "Lead",
                        "analyte_zh": "铅",
                        "food_category_zh": "食品甲",
                        "limit_mgkg": "0.1",
                        "limit_value": "0.1",
                    }
                ],
            )

            translation_calls = []

            def fake_raw(directory, filename):
                translation_calls.append((Path(directory), filename))
                return [filename]

            english_pesticide_rows = [
                (f"P{i}", "Food A", float(i)) for i in range(4)
            ]
            with (
                mock.patch.object(
                    MODULE,
                    "verify_translation_files",
                    return_value={},
                ) as verify_translations,
                mock.patch.object(MODULE, "raw", side_effect=fake_raw),
                mock.patch.object(
                    MODULE,
                    "parse_2760_en",
                    return_value=(
                        {"01.0": "Dairy products"},
                        {"01.001": "Test additive"},
                        [("01.001", "01.0", "Dairy products", 1.0)],
                    ),
                ),
                mock.patch.object(
                    MODULE,
                    "parse_2763_en",
                    return_value=english_pesticide_rows,
                ),
                mock.patch.object(
                    MODULE,
                    "parse_2762_en",
                    return_value=([], []),
                ) as parse_2762,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                MODULE.main(
                    [
                        "--release-dir",
                        str(release),
                        "--translations-dir",
                        str(translations),
                        "--report-output",
                        str(report),
                    ]
                )

            self.assertTrue(report.is_file())
            self.assertTrue((release / "food_category_names_en.csv").is_file())
            self.assertTrue((release / "additive_names_en.csv").is_file())
            verify_translations.assert_called_once_with(translations)
            self.assertEqual(
                [filename for _, filename in translation_calls],
                [
                    "GAIN_GB2760-2014_en.pdf",
                    "FSIS_GB2763-2016_en.pdf",
                    "GAIN_CH2019-0170_GB2763-2019_en.pdf",
                ],
            )
            self.assertTrue(all(directory == translations for directory, _ in translation_calls))
            parse_2762.assert_called_once_with(
                translations,
                "GAIN_CH2023-0040_GB2762-2022_en.pdf",
            )

            with (release / "food_category_names_en.csv").open(
                encoding="utf-8-sig", newline=""
            ) as handle:
                pesticide_output = [
                    row for row in csv.DictReader(handle) if row["family"] == "pesticide"
                ]
            self.assertEqual(len(pesticide_output), 1)
            self.assertEqual(pesticide_output[0]["food_key"], food_key)
            self.assertEqual(pesticide_output[0]["food_zh"], "食品甲")

            for filename in ("food_category_names_en.csv", "additive_names_en.csv"):
                output_bytes = (release / filename).read_bytes()
                self.assertNotIn(b"\r\n", output_bytes)
                self.assertTrue(output_bytes.endswith(b"\n"))
            self.assertTrue(report.read_bytes().endswith(b"\n"))


if __name__ == "__main__":
    unittest.main()
