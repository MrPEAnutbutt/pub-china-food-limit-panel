#!/usr/bin/env python3
"""Generate and freeze OCR word tables for scanned GB 2763 editions.

Outputs are written through ``*.partial`` files.  The completion manifest is
published only after every PDF page is represented in the final TSV and all
file digests have been calculated.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import numpy as np
from PIL import Image

from pesticide_ocr_integrity import (
    MANIFEST_NAME,
    MANIFEST_SCHEMA_VERSION,
    TSV_COLUMNS,
    inspect_tsv,
    sha256_file,
)


DPI = 200
STRETCH_HIGH = 230
YEARS = ("2019", "2021")
LUT = [min(255, int(value * 255 / STRETCH_HIGH)) for value in range(256)]


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a required command and surface its stderr on failure."""

    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise RuntimeError(f"command failed: {' '.join(command)}\n{detail}") from error


def tool_version(command: list[str]) -> str:
    result = run(command)
    return (result.stdout or result.stderr).splitlines()[0].strip()


def pdf_pages(path: Path) -> int:
    result = run(["pdfinfo", str(path)])
    match = re.search(r"^Pages:\s+(\d+)\s*$", result.stdout, flags=re.MULTILINE)
    if not match:
        raise RuntimeError(f"cannot determine PDF page count: {path}")
    return int(match.group(1))


def stamp_mask(image: Image.Image) -> np.ndarray:
    values = np.asarray(image).astype(np.int16)
    return (
        (values[:, :, 0] - values[:, :, 1] > 25)
        & (values[:, :, 0] - values[:, :, 2] > 25)
    )


def ocr_page(png: Path, page_number: int, writer: csv.writer) -> int:
    image = Image.open(png).convert("RGB")
    mask = stamp_mask(image)
    prepared = image.split()[0].point(LUT)
    with tempfile.TemporaryDirectory(prefix="gb2763_tesseract_") as temp_dir:
        input_path = Path(temp_dir) / "input.png"
        output_base = Path(temp_dir) / "output"
        prepared.save(input_path)
        run(
            [
                "tesseract",
                str(input_path),
                str(output_base),
                "-l",
                "chi_sim",
                "--psm",
                "6",
                "tsv",
            ]
        )
        output_path = output_base.with_suffix(".tsv")
        if not output_path.exists():
            raise RuntimeError(f"Tesseract produced no TSV for page {page_number}")
        count = 0
        with output_path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
                text = (row.get("text") or "").strip()
                if not text:
                    continue
                try:
                    x = int(row["left"])
                    y = int(row["top"])
                    width = int(row["width"])
                    height = int(row["height"])
                    confidence = float(row["conf"])
                except (KeyError, TypeError, ValueError):
                    continue
                occlusion = (
                    float(mask[y : y + height, x : x + width].mean())
                    if width > 0 and height > 0
                    else 0.0
                )
                writer.writerow(
                    [
                        page_number,
                        text,
                        x,
                        y,
                        width,
                        height,
                        f"{confidence:.0f}",
                        f"{occlusion:.3f}",
                    ]
                )
                count += 1
    if count == 0:
        raise RuntimeError(f"OCR page {page_number} contains no recognised words")
    return count


def generate_pdf(pdf_path: Path, output_path: Path) -> tuple[int, dict[str, object]]:
    page_count = pdf_pages(pdf_path)
    partial_path = output_path.with_name(output_path.name + ".partial")
    partial_path.unlink(missing_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_words = 0
    with partial_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(TSV_COLUMNS)
        with tempfile.TemporaryDirectory(prefix="gb2763_render_") as temp_dir:
            for page_number in range(1, page_count + 1):
                prefix = Path(temp_dir) / "page"
                run(
                    [
                        "pdftoppm",
                        "-f",
                        str(page_number),
                        "-l",
                        str(page_number),
                        "-r",
                        str(DPI),
                        "-png",
                        str(pdf_path),
                        str(prefix),
                    ]
                )
                rendered = [Path(path) for path in glob.glob(str(prefix) + "-*.png")]
                if len(rendered) != 1:
                    raise RuntimeError(
                        f"expected one rendered image for page {page_number}, got {len(rendered)}"
                    )
                total_words += ocr_page(rendered[0], page_number, writer)
                rendered[0].unlink()
                if page_number % 25 == 0 or page_number == page_count:
                    print(
                        f"{pdf_path.name}: {page_number}/{page_count} pages, "
                        f"{total_words} words",
                        flush=True,
                    )
        stream.flush()
        os.fsync(stream.fileno())

    metadata = inspect_tsv(partial_path, expected_pages=page_count)
    os.replace(partial_path, output_path)
    metadata["filename"] = output_path.name
    return page_count, metadata


def locate_source(source_root: Path, year: str) -> Path:
    matches = sorted(source_root.rglob(f"GB 2763-{year}*.pdf"))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one GB 2763-{year} source PDF, found {len(matches)}"
        )
    return matches[0]


def find_language_pack() -> Path:
    result = run(["tesseract", "--list-langs"])
    first_line = (result.stdout or result.stderr).splitlines()[0]
    match = re.search(r'"([^"]+)"', first_line)
    if not match:
        raise RuntimeError("cannot locate Tesseract language-data directory")
    path = Path(match.group(1)) / "chi_sim.traineddata"
    if not path.exists():
        raise RuntimeError(f"missing Tesseract language pack: {path}")
    return path


def write_manifest(output_dir: Path, editions: dict[str, dict[str, object]]) -> Path:
    language_pack = find_language_pack()
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "completed_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "pipeline": {
            "render": {
                "tool": "pdftoppm",
                "version": tool_version(["pdftoppm", "-v"]),
                "dpi": DPI,
                "format": "png",
            },
            "preprocessing": {
                "colour_channel": "red",
                "linear_stretch_input_range": [0, STRETCH_HIGH],
                "seal_mask": "R-G>25 and R-B>25",
            },
            "ocr": {
                "tool": "tesseract",
                "version": tool_version(["tesseract", "--version"]),
                "language": "chi_sim",
                "page_segmentation_mode": 6,
                "output_format": "tsv",
                "command_template": [
                    "tesseract",
                    "<prepared-page.png>",
                    "<output-base>",
                    "-l",
                    "chi_sim",
                    "--psm",
                    "6",
                    "tsv",
                ],
                "language_pack": {
                    "filename": language_pack.name,
                    "file_size_bytes": language_pack.stat().st_size,
                    "sha256": sha256_file(language_pack),
                },
            },
        },
        "editions": editions,
    }
    manifest_path = output_dir / MANIFEST_NAME
    partial_path = manifest_path.with_name(manifest_path.name + ".partial")
    partial_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with partial_path.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(partial_path, manifest_path)
    return manifest_path


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "Data/Interim/pesticide_ocr",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        choices=YEARS,
        default=list(YEARS),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    editions: dict[str, dict[str, object]] = {}
    try:
        for year in args.years:
            pdf_path = locate_source(args.source_root.resolve(), year)
            output_path = output_dir / f"ocr_words_{year}.tsv"
            page_count, ocr_metadata = generate_pdf(pdf_path, output_path)
            editions[year] = {
                "source_pdf": {
                    "filename": pdf_path.name,
                    "file_size_bytes": pdf_path.stat().st_size,
                    "sha256": sha256_file(pdf_path),
                    "page_count": page_count,
                },
                "ocr_tsv": ocr_metadata,
            }
        manifest_path = write_manifest(output_dir, editions)
    except Exception:
        (output_dir / MANIFEST_NAME).unlink(missing_ok=True)
        raise
    print(f"Frozen OCR completion manifest: {manifest_path}")


if __name__ == "__main__":
    main()
