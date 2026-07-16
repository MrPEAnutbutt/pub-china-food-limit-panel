import unittest

from Program.Clean.build_version_timeline import (
    build_coverage_date_rows,
    portable_locator,
)


def manifest_row(
    source_id: str,
    family: str,
    standard: str,
    year: str,
    filename: str,
) -> dict[str, str]:
    return {
        "source_id": source_id,
        "family": family,
        "standard": standard,
        "version_year": year,
        "source_filename": filename,
    }


def cover_row(
    standard: str,
    year: str,
    issue_date: str,
    effective_date: str,
    date_source: str,
) -> dict[str, str]:
    return {
        "number": standard,
        "version_year": year,
        "issue_date": issue_date,
        "effective_date": effective_date,
        "date_source": date_source,
        "cross_check_official_register": "",
    }


def timeline_row(
    standard: str,
    year: str,
    issue_date: str = "",
    effective_date: str = "",
) -> dict[str, object]:
    return {
        "std_id": standard,
        "year": year,
        "event_type": "正式版",
        "发布日期": issue_date,
        "实施日期": effective_date,
    }


class CoverageVersionDateTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            ("MOA Announcement 235", "2002"): manifest_row(
                "SRC0015",
                "veterinary_drug",
                "MOA Announcement 235",
                "2002",
                "archive/vet/农业部235号公告-2002.doc",
            ),
            ("GB 31650", "2019"): manifest_row(
                "SRC0016",
                "veterinary_drug",
                "GB 31650",
                "2019",
                "archive/vet/GB 31650-2019.pdf",
            ),
            ("GB 31650.1", "2022"): manifest_row(
                "SRC0017",
                "veterinary_drug",
                "GB 31650.1",
                "2022",
                "archive/vet/GB 31650.1-2022.pdf",
            ),
            ("GB 2760", "1996"): manifest_row(
                "SRC0018",
                "additive",
                "GB 2760",
                "1996",
                "archive/additive/GB 2760-1996.pdf",
            ),
        }
        self.cover_dates = {
            ("MOA Announcement 235", "2002"): cover_row(
                "MOA Announcement 235",
                "2002",
                "2002-12-24",
                "2002-12-24",
                "announcement text",
            ),
            ("GB 31650", "2019"): cover_row(
                "GB 31650",
                "2019",
                "2019-09-06",
                "2020-04-01",
                "cover text layer",
            ),
            ("GB 31650.1", "2022"): cover_row(
                "GB 31650.1",
                "2022",
                "2022-09-20",
                "2023-02-01",
                "cover OCR",
            ),
            ("GB 2760", "1996"): cover_row(
                "GB 2760",
                "1996",
                "",
                "",
                "no date on cover",
            ),
        }
        self.timeline = [
            timeline_row("MOA Announcement 235", "2002"),
            timeline_row("GB 31650", "2019", "2019-09-06", "2020-04-01"),
            timeline_row("GB 31650.1", "2022", "2022-09-20", "2023-02-01"),
            timeline_row("GB 2760", "1996"),
        ]

    def test_merge_retains_full_scope_and_distinct_veterinary_identities(self):
        rows = build_coverage_date_rows(
            self.manifest,
            self.cover_dates,
            self.timeline,
        )

        self.assertEqual(len(rows), 4)
        self.assertEqual(
            {row["standard"] for row in rows if row["family"] == "veterinary_drug"},
            {"MOA Announcement 235", "GB 31650", "GB 31650.1"},
        )
        by_identity = {(row["standard"], row["version_year"]): row for row in rows}
        undated = by_identity[("GB 2760", "1996")]
        self.assertEqual(undated["date_status"], "not_printed")
        self.assertEqual(undated["issue_date"], "")
        self.assertEqual(undated["date_source"], "not printed")
        self.assertEqual(
            by_identity[("GB 31650", "2019")]["date_resolution"],
            "cover_and_official_register_agree",
        )
        self.assertEqual(
            by_identity[("GB 31650", "2019")]["date_source"],
            "text layer",
        )
        self.assertEqual(
            by_identity[("MOA Announcement 235", "2002")]["date_resolution"],
            "source_document_only",
        )
        self.assertTrue(all("/" not in row["source_filename"] for row in rows))

    def test_manifest_and_cover_scope_must_match_exactly(self):
        shortened = dict(self.cover_dates)
        shortened.pop(("GB 2760", "1996"))

        with self.assertRaisesRegex(ValueError, "must exactly match"):
            build_coverage_date_rows(self.manifest, shortened, self.timeline)

    def test_register_date_conflict_fails_closed(self):
        conflicting = list(self.timeline)
        conflicting[1] = timeline_row(
            "GB 31650",
            "2019",
            "2019-09-07",
            "2020-04-01",
        )

        with self.assertRaisesRegex(ValueError, "dates conflict"):
            build_coverage_date_rows(
                self.manifest,
                self.cover_dates,
                conflicting,
            )

    def test_portable_locator_handles_posix_and_windows_paths(self):
        self.assertEqual(
            portable_locator("/Volumes/archive/GB 2762-2022.pdf"),
            "GB 2762-2022.pdf",
        )
        self.assertEqual(
            portable_locator(r"D:\\archive\\GB 2763-2021.pdf"),
            "GB 2763-2021.pdf",
        )


if __name__ == "__main__":
    unittest.main()
