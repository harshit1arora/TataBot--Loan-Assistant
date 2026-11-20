"""Recover the quiesced demo in a separate directory and compare the entire loan record."""

import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from recovery import DATABASES, digest, transfer


def drill(source):
    with tempfile.TemporaryDirectory() as tmp:
        backup, restored = Path(tmp) / "backup", Path(tmp) / "restored"
        transfer("backup", source, backup)
        transfer("restore", backup, restored)
        for name in DATABASES:
            with (
                closing(sqlite3.connect(source / name)) as a,
                closing(sqlite3.connect(restored / name)) as b,
            ):
                assert list(a.iterdump()) == list(b.iterdump()), name
                if name == "core.db":
                    assert b.execute("""SELECT count(*) FROM applications a JOIN pilot_quotes q ON q.application_id=a.id
                        JOIN decisions d ON d.application_id=a.id JOIN document_reviews r ON r.application_id=a.id
                        WHERE a.status='sanctioned' AND d.outcome='approve'""").fetchone()[0]
                    for key, checksum in b.execute("SELECT storage_key, sha256 FROM documents"):
                        assert digest(restored / "storage" / key) == checksum
                else:
                    assert b.execute("SELECT count(*) FROM conversation_turn_traces").fetchone()[0]
                svc = name.split(".")[0]
                # Reproduce a populated revision-1 deployment, then run the normal startup upgrader twice.
                index = "ix_review_queue" if svc == "core" else "ix_session_trace_time"
                b.execute(f"DROP INDEX {index}")
                b.execute(f"DELETE FROM tatabot_{svc}_revision WHERE revision>=2")
                b.commit()
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    f"from {svc}_service.db import create_all; create_all(); create_all()",
                ],
                cwd=Path(__file__).resolve().parents[1] / "services" / svc,
                env=dict(os.environ, DATABASE_URL="sqlite:///" + (restored / name).as_posix()),
                check=True,
            )
            with closing(sqlite3.connect(restored / name)) as b:
                assert b.execute(
                    "SELECT count(*) FROM sqlite_master WHERE name=?", (index,)
                ).fetchone()[0]
        print(
            "Recovery verified: quote, approved decision, review, trace, document checksums and populated schema upgrade."
        )
        with (backup / "core.db").open("ab") as out:
            out.write(b"corrupt")
        try:
            transfer("restore", backup, Path(tmp) / "invalid")
        except ValueError:
            pass
        else:
            raise AssertionError("Corrupt backup accepted")


if __name__ == "__main__":
    drill(Path(sys.argv[1]).resolve())
