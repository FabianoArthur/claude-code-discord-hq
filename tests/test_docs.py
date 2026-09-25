import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MARKDOWN = sorted(
    p
    for p in REPO.glob("**/*.md")
    if not any(part.startswith(".") and part != ".github" for part in p.relative_to(REPO).parts)
    and ".venv" not in p.parts
)
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


@pytest.mark.parametrize("doc", MARKDOWN, ids=lambda p: str(p.relative_to(REPO)))
def test_relative_links_point_to_existing_files(doc):
    text = re.sub(r"`[^`]*`", "", doc.read_text())  # inline code is not a link
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        assert (doc.parent / target).exists(), f"{doc.relative_to(REPO)} links to missing {target}"


@pytest.mark.parametrize("readme", ["README.md", "README.pt-BR.md"])
def test_quickstart_has_fewer_than_10_steps(readme):
    text = (REPO / readme).read_text()
    section = re.split(r"^## ", text, flags=re.M)
    quick = next(s for s in section if s.startswith(("Quickstart", "Início rápido")))
    steps = re.findall(r"^\d+\. ", quick, flags=re.M)
    assert 0 < len(steps) < 10


def test_both_readmes_cover_the_same_sections():
    english = re.findall(r"^## ", (REPO / "README.md").read_text(), flags=re.M)
    portuguese = re.findall(r"^## ", (REPO / "README.pt-BR.md").read_text(), flags=re.M)
    assert len(english) == len(portuguese)
