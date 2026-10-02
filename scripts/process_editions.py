"""Only current dated, explicitly publishable intakes enter the worker."""
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import subprocess
import sys

from rss_to_wp.editions.publisher import expected_date


def submitted_paths():
    """A new edition must not automatically retry an earlier uncertain edition."""
    if os.environ.get("GITHUB_EVENT_NAME") != "push":
        return None  # Explicit manual dispatch; dry-run defaults true.
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    before, after = event["before"], event["after"]
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (before, after)):
        raise ValueError("Invalid event commit")
    diff = subprocess.run(["git", "diff", "--name-only", before, after,
                           "--", "editions/inbox"], capture_output=True, text=True, check=True)
    return set(diff.stdout.splitlines())


def main():
    now = datetime.now(timezone.utc)
    failed = False
    output = Path("edition-output")
    output.mkdir(exist_ok=True)
    outcomes = []
    submitted = submitted_paths()
    for edition in ("scores", "preview"):
        day = expected_date(edition, now).isoformat()
        path = Path("editions/inbox") / f"{edition}-{day}.json"
        if submitted is not None and str(path) not in submitted:
            continue
        if not path.is_file():
            outcomes.append({"edition": edition, "date": day, "state": "no_intake"})
            continue
        try:
            intake = json.loads(path.read_text())
            if intake.get("edition") != edition or intake.get("date") != day:
                raise ValueError("Wrong edition in dated file")
        except (ValueError, OSError):
            outcomes.append({"edition": edition, "date": day, "state": "invalid_intake"})
            failed = True
            continue
        command = [sys.executable, "-m", "rss_to_wp.editions.publisher", str(path),
                   "--output", str(output / f"{edition}-{day}")]
        if os.environ.get("EDITION_DRY_RUN", "true").lower() != "false":
            command.append("--dry-run")
        result = subprocess.run(command, check=False)
        failed = failed or result.returncode != 0
        outcomes.append({"edition": edition, "date": day, "exit_code": result.returncode})
    summary = json.dumps(outcomes, indent=2)
    (output / "intakes.json").write_text(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write("## Daily edition results\n\n```json\n" + summary + "\n```\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
