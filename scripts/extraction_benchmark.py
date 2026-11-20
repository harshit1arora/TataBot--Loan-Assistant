"""Reproducible labelled synthetic payslip benchmark for PDF and OCR extractors."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "core"))

from core_service.extractors import OcrExtractor, TextPdfExtractor  # noqa: E402
from core_service.ocr import build_ocr  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402


def cases(count, seed):
    rng = random.Random(seed)
    names = ["Anita Rao", "Kiran Mehta", "Priya Nair", "Sanjay Kumar", "Asha Sharma"]
    firms = ["Aster Systems", "Bluebird Services", "Cedar Labs", "Delta Works"]
    labels = ["Net Pay", "NET PAY", "Net Payable", "Net Salary", "Gross Salary", "Monthly Income"]
    for i in range(count):
        net = rng.randrange(18000, 190000, 500)
        gross = net + rng.randrange(2000, 15000, 1000)
        yield {
            "id": i,
            "name": names[i % len(names)],
            "employer": firms[(i // 3) % len(firms)],
            "income_paise": net * 100,
            "gross": gross,
            "label": labels[(i // 2) % len(labels)],
            "noise_seed": rng.randrange(2**32),
            "variant": i % 4,
        }


def lines(case):
    # Ground truth is net pay. Gross Salary and unfamiliar labels deliberately test mistakes.
    return [
        "PAYROLL STATEMENT",
        f"Employee Name: {case['name']}",
        f"Employer: {case['employer']}",
        f"Gross Salary: {case['gross']:,}",
        f"{case['label']}: {case['income_paise'] // 100:,}",
        "Salary period: 2026 July",
    ]


def pdf(case):
    out = BytesIO()
    doc = canvas.Canvas(out, pagesize=(612, 792))
    doc.setFont(["Helvetica", "Times-Roman", "Courier", "Helvetica-Bold"][case["variant"]], 12)
    for index, line in enumerate(lines(case)):
        doc.drawString(40 + case["variant"] * 7, 730 - index * 38, line)
    doc.save()
    return out.getvalue()


def image(case):
    out = BytesIO()
    pic = Image.new("RGB", (1200, 700), "white")
    draw = ImageDraw.Draw(pic)
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    available = [p for p in candidates if Path(p).exists()]
    font = (
        ImageFont.truetype(available[case["variant"] % len(available)], 31)
        if available
        else ImageFont.load_default()
    )
    for index, line in enumerate(lines(case)):
        draw.text((50 + 10 * case["variant"], 40 + index * 90), line, fill=(20, 20, 20), font=font)
    rng = random.Random(case["noise_seed"])
    for _ in range(case["variant"] * 400):
        x, y = rng.randrange(pic.width), rng.randrange(pic.height)
        draw.point((x, y), fill=(160, 160, 160))
    if case["variant"] == 3:
        pic = pic.filter(ImageFilter.GaussianBlur(0.7))
    pic.save(out, format="PNG")
    return out.getvalue()


def summarise(rows):
    result = {}
    for path in ("text_pdf", "ocr"):
        group = [r for r in rows if r["path"] == path]
        if not group:
            continue
        fields = {}
        for field in ("income_paise", "name", "employer"):
            fields[field] = sum(r["correct"][field] for r in group) / len(group)
        buckets = defaultdict(list)
        for row in group:
            buckets[f"{row['confidence']:.1f}"].append(row["correct"]["income_paise"])
        thresholds = []
        for threshold in (0.5, 0.7, 0.75, 0.85, 0.9):
            accepted = [r for r in group if r["confidence"] >= threshold and r["has_income"]]
            errors = [r for r in group if not r["correct"]["income_paise"]]
            thresholds.append(
                {
                    "threshold": threshold,
                    "review_share": 1 - len(accepted) / len(group),
                    "accepted_income_accuracy": sum(r["correct"]["income_paise"] for r in accepted)
                    / len(accepted)
                    if accepted
                    else None,
                    "review_error_precision": sum(r not in accepted for r in errors)
                    / (len(group) - len(accepted))
                    if len(group) != len(accepted)
                    else None,
                    "error_review_recall": sum(r not in accepted for r in errors) / len(errors)
                    if errors
                    else None,
                }
            )
        result[path] = {
            "n": len(group),
            "field_accuracy": fields,
            "confidence_calibration": {
                k: {"n": len(v), "income_accuracy": sum(v) / len(v)}
                for k, v in sorted(buckets.items())
            },
            "thresholds": thresholds,
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=240)
    parser.add_argument("--seed", type=int, default=731)
    parser.add_argument("--ocr", choices=["rapidocr", "tesseract", "disabled"], default="rapidocr")
    parser.add_argument("--output", required=True)
    parser.add_argument("--dataset-dir", type=Path, help="write labelled PDF and PNG fixtures")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("count must be positive")
    provider = build_ocr(args.ocr)
    if args.ocr != "disabled" and not provider.available():
        raise SystemExit(f"OCR provider {args.ocr} is unavailable")
    rows = []
    dataset = []
    if args.dataset_dir:
        args.dataset_dir.mkdir(parents=True, exist_ok=True)
    for case in cases(args.count, args.seed):
        pdf_data = pdf(case)
        image_data = image(case) if args.ocr != "disabled" or args.dataset_dir else None
        if args.dataset_dir:
            (args.dataset_dir / f"{case['id']:03}.pdf").write_bytes(pdf_data)
            (args.dataset_dir / f"{case['id']:03}.png").write_bytes(image_data)
            dataset.append(case)
        paths = [("text_pdf", TextPdfExtractor().extract(pdf_data, 0.75))]
        if args.ocr != "disabled":
            paths.append(("ocr", OcrExtractor(provider).extract(image_data, 0.75)))
        for path, result in paths:
            rows.append(
                {
                    "id": case["id"],
                    "path": path,
                    "truth": {key: case[key] for key in ("income_paise", "name", "employer")},
                    "extracted": {
                        "income_paise": result.income_paise,
                        "name": result.fields.get("name"),
                        "employer": result.fields.get("employer"),
                    },
                    "confidence": result.confidence,
                    "has_income": result.income_paise is not None,
                    "correct": {
                        "income_paise": result.income_paise == case["income_paise"],
                        "name": result.fields.get("name") == case["name"],
                        "employer": result.fields.get("employer") == case["employer"],
                    },
                }
            )
    if args.dataset_dir:
        (args.dataset_dir / "labels.json").write_text(
            json.dumps(dataset, indent=2), encoding="utf-8"
        )
    report = {
        "seed": args.seed,
        "cases": args.count,
        "ocr_provider": args.ocr,
        "results": summarise(rows),
        "rows": rows,
    }
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["results"], indent=2))


if __name__ == "__main__":
    main()
