from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import EXPORT_DIR
from app.db import Opportunity, ReportFile, utcnow
from app.pipeline import CSV_HEADERS, opportunity_row
from app.security.text import write_csv


def write_report(session: Session, run_id: str, report_date: str) -> ReportFile:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    opportunities = session.scalars(select(Opportunity).where(Opportunity.run_id == run_id)).all()
    rows = [opportunity_row(session, item) for item in opportunities]
    csv_text = write_csv(CSV_HEADERS, rows)
    payload = {
        "run_id": run_id,
        "report_date": report_date,
        "count": len(rows),
        "opportunities": [dict(zip(CSV_HEADERS, row, strict=False)) for row in rows],
    }
    stem = f"goip-{report_date}-{run_id[:8]}"
    csv_path = EXPORT_DIR / f"{stem}.csv"
    json_path = EXPORT_DIR / f"{stem}.json"
    csv_path.write_text(csv_text, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    existing = session.scalar(select(ReportFile).where(ReportFile.run_id == run_id))
    if existing:
        existing.csv_path = str(csv_path)
        existing.json_path = str(json_path)
        existing.report_date = report_date
        session.commit()
        return existing
    report = ReportFile(
        id=str(uuid.uuid4()),
        run_id=run_id,
        report_date=report_date,
        csv_path=str(csv_path),
        json_path=str(json_path),
        created_at=utcnow(),
    )
    session.add(report)
    session.commit()
    return report


def read_export(path: str) -> bytes:
    file = Path(path).resolve()
    root = EXPORT_DIR.resolve()
    if root not in file.parents and file != root:
        raise ValueError("Export path escapes the export directory")
    return file.read_bytes()
