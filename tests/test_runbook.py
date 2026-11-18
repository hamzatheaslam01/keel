import re
from pathlib import Path

HEADINGS = ["## 1. Prerequisites", "## 2. Models and tokenizers", "## 3. Start llama.cpp",
            "## 4. Configure Keel", "## 5. Smoke test", "## 6. Measure seconds per episode",
            "## 7. Full run and resume", "## 8. Kaggle", "## 9. Hosted model (M3)",
            "## 10. Report", "## 11. Troubleshooting"]


def test_runbook_sections():
    text = Path("docs/RUNBOOK.md").read_text(encoding="utf-8")
    for h in HEADINGS:
        assert h in text
    assert "--jinja" in text and "enable_thinking" in text
    assert not re.search(r"\d+\s*GPU-hours/week", text)
