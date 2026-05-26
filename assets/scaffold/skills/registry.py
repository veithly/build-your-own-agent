from __future__ import annotations

from pathlib import Path


BUNDLED_DIR = Path(__file__).parent / "bundled"


def list_bundled_skill_names() -> list[str]:
    if not BUNDLED_DIR.exists():
        return []
    return sorted(path.stem for path in BUNDLED_DIR.glob("*.md"))


def load_skill(name: str) -> str | None:
    path = BUNDLED_DIR / f"{name}.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")
