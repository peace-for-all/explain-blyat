"""Export only reviewed source paths, never local data or Git history."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ".env.example", ".gitignore", "README.md", "LICENSE", "CONTRIBUTING.md",
    "pyproject.toml", "MANIFEST.in", ".github/workflows/tests.yml",
    "scripts/export_source.py", "setup.sh", "run",
]
PATTERNS = ["explain_video/*.py", "explain_video/*.html", "tests/test_*.py", "docs/*.md"]


def main():
    paths = [ROOT / name for name in FILES]
    for pattern in PATTERNS:
        paths.extend(sorted(ROOT.glob(pattern)))
    for path in paths:
        if not path.is_file() or any(p.is_symlink() for p in [path, *path.parents] if p != ROOT.parent):
            raise ValueError(f"Expected a regular source file without symlinks: {path}")
    target = ROOT / "dist" / "explain-video-source.zip"
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, Path("explain-blyat") / path.relative_to(ROOT))
    print(f"Exported {len(paths)} source files to {target}")


if __name__ == "__main__":
    main()
