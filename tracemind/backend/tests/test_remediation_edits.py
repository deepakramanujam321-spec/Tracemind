"""Search/replace edit path of the remediation engine (apply_edits). Pure-filesystem tests, no Docker."""
import pytest
from tracemind.remediation.models import Edit
from tracemind.remediation.patching import PatchRejected, apply_edits


@pytest.fixture
def sb(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    (tmp_path / "dup.py").write_text("z\nz\n")
    return tmp_path


def test_exact_edit_applies(sb):
    assert apply_edits(sb, [Edit(path="a.py", search="y = 2", replace="y = 3")]) == ["a.py"]
    assert (sb / "a.py").read_text() == "x = 1\ny = 3\n"


def test_create_new_file(sb):
    apply_edits(sb, [Edit(path="sub/new.sql", search="", replace="select 1;\n")])
    assert (sb / "sub/new.sql").read_text() == "select 1;\n"


@pytest.mark.parametrize("edit,why", [
    (Edit(path="a.py", search="missing", replace="q"), "exactly once"),
    (Edit(path="dup.py", search="z", replace="q"), "exactly once"),
    (Edit(path="nope.py", search="x", replace="q"), "does not exist"),
    (Edit(path="a.py", search="", replace="q"), "file exists"),
    (Edit(path="../evil.py", search="", replace="q"), "unsafe path"),
    (Edit(path=".git/hooks/pre-commit", search="", replace="q"), "unsafe path"),
    (Edit(path="/etc/passwd", search="x", replace="q"), "unsafe path"),
])
def test_bad_edits_rejected_and_nothing_written(sb, edit, why):
    before = {p.name: p.read_text() for p in sb.iterdir() if p.is_file()}
    with pytest.raises(PatchRejected, match=why):
        apply_edits(sb, [Edit(path="a.py", search="x = 1", replace="x = 9"), edit])  # a good edit first: must not persist
    assert {p.name: p.read_text() for p in sb.iterdir() if p.is_file()} == before


def test_symlink_not_followed(sb, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "t.txt"
    outside.write_text("secret")
    (sb / "link.txt").symlink_to(outside)
    with pytest.raises(PatchRejected):
        apply_edits(sb, [Edit(path="link.txt", search="secret", replace="pwned")])
    assert outside.read_text() == "secret"
