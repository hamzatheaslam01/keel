import re
from pathlib import Path

HEADINGS = ["# Keel", "## Quickstart (pip)", "## Quickstart (Docker)", "## Point your agent at Keel",
            "## Guards", "## Headers", "## Benchmark: DecayBench-lite", "## Results",
            "## Trace viewer", "## How it works", "## License"]


def test_readme_sections():
    text = Path("README.md").read_text(encoding="utf-8")
    for h in HEADINGS:
        assert h in text
    assert "X-Keel-Session" in text and "keel bench run" in text
    results = text.split("## Results")[1].split("## Trace viewer")[0]
    assert not re.search(r"\d%", results)
