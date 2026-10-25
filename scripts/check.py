"""Check scaffold files and installed entry points using the standard library."""

import compileall
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def check_files() -> None:
    """Validate source syntax, metadata, JSON and local Markdown file links."""
    for directory in (ROOT / "src", ROOT / "scripts"):
        if not compileall.compile_dir(directory, quiet=1):
            raise ValueError(f"Invalid Python syntax in {directory}")
    with (ROOT / "pyproject.toml").open("rb") as source:
        tomllib.load(source)
    for path in (ROOT / "reports").rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))

    markdown = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "AGENTS.md"]
    for directory in (
        "docs", "reports", "configs", "maps", "schemas",
        "examples", "tests", "web", "artifacts",
    ):
        markdown.extend((ROOT / directory).rglob("*.md"))
    markdown.append(ROOT / "bedwars_sim_research_resources.md")
    for path in markdown:
        content = path.read_text(encoding="utf-8")
        content = re.sub(r"^```[^\n]*\n.*?^```[^\n]*$", "", content, flags=re.M | re.S)
        content = re.sub(r"`[^`\n]*`", "", content)
        for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", content):
            link = urlsplit(target.strip("<>"))
            if link.scheme or link.netloc or not link.path:
                continue
            if not (path.parent / unquote(link.path)).exists():
                raise ValueError(f"Broken link in {path.relative_to(ROOT)}: {target}")


def check_entry_points() -> None:
    """Run installed module and console entry points outside the checkout."""
    console = Path(sys.executable).parent / "bedwars-arena"
    with tempfile.TemporaryDirectory(prefix="bedwars-arena-smoke-") as directory:
        for command in (
            [sys.executable, "-m", "bedwars_arena", "--help"],
            [sys.executable, "-m", "bedwars_arena", "--version"],
            [str(console), "--help"],
        ):
            subprocess.run(command, cwd=directory, check=True, capture_output=True, text=True)
        result = subprocess.run(
            [str(console), "info", "--json"],
            cwd=directory,
            check=True,
            capture_output=True,
            text=True,
        )
        json.loads(result.stdout)


if __name__ == "__main__":
    try:
        check_files()
        check_entry_points()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Scaffold check failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Scaffold checks passed: syntax, metadata, JSON, local links and installed CLI.")
