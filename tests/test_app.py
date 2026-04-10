import subprocess
from pathlib import Path
from typing import List

import pytest
from conftest import (
    BREAKING_FEATURE_IN_BODY,
    CHORE,
    FEATURE,
    FIX,
    INITIAL_COMMIT,
    SQUASHED_MERGE_WITH_IGNORED,
    GitFactory,
)

from convbump.__main__ import _run, ignore_commit
from convbump.conventional import CommitType, ConventionalCommit
from convbump.git import Git
from convbump.version import DEFAULT_FIRST_VERSION


def test_new_repo(create_git_repository: GitFactory) -> None:
    git = create_git_repository([INITIAL_COMMIT])
    next_version, _ = _run(git, False)
    assert next_version == DEFAULT_FIRST_VERSION


def test_not_version_tag(create_git_repository: GitFactory) -> None:
    git = create_git_repository([(INITIAL_COMMIT, "not-a-version"), FEATURE])
    next_version, _ = _run(git, False)
    assert next_version == DEFAULT_FIRST_VERSION


def test_no_new_commits_after_tag(create_git_repository: GitFactory) -> None:
    git = create_git_repository([(INITIAL_COMMIT, "v1.0.0")])
    with pytest.raises(ValueError):
        _run(git, False)


def test_no_conventional_commit_after_tag_strict(
    create_git_repository: GitFactory,
) -> None:
    git = create_git_repository([(INITIAL_COMMIT, "v1.0.0"), "Non-conventional commit"])
    with pytest.raises(ValueError):
        _run(git, True)


def test_no_conventional_commit_after_tag_not_strict(
    create_git_repository: GitFactory,
) -> None:
    git = create_git_repository([(INITIAL_COMMIT, "v1.0.0"), "Non-conventional commit"])
    with pytest.raises(ValueError):
        _run(git, False)


def test_find_last_valid_version_tag(create_git_repository: GitFactory) -> None:
    git = create_git_repository(
        [
            (INITIAL_COMMIT, "v0.1.0"),
            ("Second commit", "not-a-version"),
            BREAKING_FEATURE_IN_BODY,
        ]
    )
    next_version, _ = _run(git, False)
    assert next_version == DEFAULT_FIRST_VERSION.bump_major()


def test_non_conventional_commits_strict(create_git_repository: GitFactory) -> None:
    git = create_git_repository(
        [(INITIAL_COMMIT, "v0.1.0"), FEATURE, "Non-conventional commit"]
    )
    with pytest.raises(ValueError):
        _run(git, True)


def test_non_conventional_commits_not_strict(create_git_repository: GitFactory) -> None:
    git = create_git_repository(
        [(INITIAL_COMMIT, "v0.1.0"), FEATURE, "Non-conventional commit"]
    )
    next_version, _ = _run(git, False)
    assert next_version == DEFAULT_FIRST_VERSION.bump_minor()


def test_conventional_commits(create_git_repository: GitFactory) -> None:
    git = create_git_repository([(INITIAL_COMMIT, "v0.1.0"), FEATURE, FIX])
    next_version, _ = _run(git, False)
    assert next_version == DEFAULT_FIRST_VERSION.bump_minor()


@pytest.mark.parametrize(
    "patterns, commit, result",
    [
        (
            ["aiohttp"],
            ConventionalCommit(
                CommitType.CHORE,
                "deps",
                False,
                "Update aiohttp",
                "",
                "",
                "chore(deps): Update aiohttp",
            ),
            True,
        ),
        (
            ["aiohttp"],
            ConventionalCommit(
                CommitType.CHORE,
                "deps",
                False,
                "Update deps",
                "Update aiohttp",
                "",
                "chore(deps): Update aiohttp",
            ),
            True,
        ),
        (
            ["deps"],
            ConventionalCommit(
                CommitType.CHORE,
                "deps",
                False,
                "Update aiohttp",
                "",
                "",
                "chore(deps): Update aiohttp",
            ),
            True,
        ),
        (
            ["chore"],
            ConventionalCommit(
                CommitType.CHORE,
                "deps",
                False,
                "Update aiohttp",
                "",
                "",
                "chore(deps): Update aiohttp",
            ),
            True,
        ),
        (
            ["feat", "aiohttp"],
            ConventionalCommit(
                CommitType.CHORE,
                "deps",
                False,
                "Update aiohttp",
                "",
                "",
                "chore(deps): Update aiohttp",
            ),
            True,
        ),
        (
            [""],
            ConventionalCommit(
                CommitType.CHORE,
                "deps",
                False,
                "Update aiohttp",
                "",
                "",
                "chore(deps): Update aiohttp",
            ),
            False,
        ),
        (
            ["formatting"],
            ConventionalCommit(
                CommitType.CHORE,
                "deps",
                False,
                "Update aiohttp",
                "",
                "",
                "chore(deps): Update aiohttp",
            ),
            False,
        ),
        (
            ["ci:"],
            ConventionalCommit(
                CommitType.FEAT,
                None,
                False,
                "Add new feature",
                "ci: update build scripts\ndocs: update readme",
                "",
                "feat: Add new feature",
            ),
            False,  # Should NOT be ignored - pattern only in body, not in subject
        ),
    ],
)
def test_ignore_commit(
    patterns: List[str], commit: ConventionalCommit, result: bool
) -> None:
    assert ignore_commit(patterns, commit) is result


def test_ignore_prefix(create_git_repository: GitFactory) -> None:
    git = create_git_repository([(INITIAL_COMMIT, "v0.1.0"), CHORE])

    with pytest.raises(
        ValueError
    ):  # The chore commit should be skipped, so there are no new commits left
        _run(git, False, ignored_patterns=["chore"])


def test_regular_commit_with_body_containing_ignored_patterns(
    create_git_repository: GitFactory,
) -> None:
    """Test that a regular commit (conv commit in subject) with body containing
    ignored patterns is NOT ignored.

    This simulates the case where a commit has a conventional commit in the subject
    but the body contains squashed commit messages (like from a PR) with ci: or docs:
    prefixes. The commit should NOT be ignored because the ignore patterns should only
    check the subject, not the body.
    """
    # Create a commit with feat: in subject but body containing ci: and docs:
    commit_with_body = (
        "feat: Implement user authentication\n\n"
        "This PR includes:\n"
        "- ci: update build pipeline\n"
        "- docs: update API documentation\n"
        "- feat: add login endpoint\n"
    )
    git = create_git_repository([(INITIAL_COMMIT, "v0.1.0"), commit_with_body])

    # With "ci:" ignored - should still process the commit (feat in subject)
    next_version, _ = _run(git, False, ignored_patterns=["ci:"])
    assert next_version == DEFAULT_FIRST_VERSION.bump_minor()  # feat -> minor bump

    # With "docs:" ignored - should still process the commit (feat in subject)
    next_version, _ = _run(git, False, ignored_patterns=["docs:"])
    assert next_version == DEFAULT_FIRST_VERSION.bump_minor()  # feat -> minor bump


def test_squashed_merge_with_ignored_commits(create_git_repository: GitFactory) -> None:
    """Test that squashed commits properly handle ignored patterns.

    The squashed commit contains:
    - chore: update dependencies (should be ignored with "chore" pattern)
    - fix: critical security fix (should not be ignored)
    - feat: add new dashboard (should not be ignored)
    - chore: update build scripts (should be ignored with "chore" pattern)

    With "chore" ignored, should select feat (highest priority among non-ignored).
    """
    git = create_git_repository(
        [(INITIAL_COMMIT, "v0.1.0"), SQUASHED_MERGE_WITH_IGNORED]
    )

    # Without ignore patterns - should select feat (highest priority)
    next_version_no_ignore, _ = _run(git, False)
    assert (
        next_version_no_ignore == DEFAULT_FIRST_VERSION.bump_minor()
    )  # feat -> minor bump

    # With "chore" ignored - should still select feat (highest among non-ignored)
    next_version_ignore_chore, _ = _run(git, False, ignored_patterns=["chore"])
    assert (
        next_version_ignore_chore == DEFAULT_FIRST_VERSION.bump_minor()
    )  # feat -> minor bump

    # With "feat" ignored - should select fix (highest among non-ignored)
    next_version_ignore_feat, _ = _run(git, False, ignored_patterns=["feat"])
    assert (
        next_version_ignore_feat == DEFAULT_FIRST_VERSION.bump_patch()
    )  # fix -> patch bump

    # With both "feat" and "fix" ignored - should select chore (patch bump)
    next_version_ignore_feat_fix, _ = _run(git, False, ignored_patterns=["feat", "fix"])
    assert (
        next_version_ignore_feat_fix == DEFAULT_FIRST_VERSION.bump_patch()
    )  # chore -> patch bump

    # With all commit types ignored - should raise ValueError (no commits left)
    with pytest.raises(ValueError):  # No conventional commits left after ignoring
        _run(git, False, ignored_patterns=["feat", "fix", "chore"])


def _commit_file(repo_path: Path, directory: str, filename: str, message: str) -> None:
    """Create a file in the given directory and commit it."""
    dir_path = repo_path / directory
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / filename
    file_path.write_text(message)
    subprocess.check_call(["git", "add", "."], cwd=repo_path)
    subprocess.check_call(["git", "commit", "-m", message], cwd=repo_path)


def _init_repo_with_tag(tmp_path: Path, tag: str) -> Git:
    """Initialize a repo with a single commit and tag."""
    subprocess.check_call(["git", "init"], cwd=tmp_path)
    subprocess.check_call(
        ["git", "commit", "--allow-empty", "-m", INITIAL_COMMIT], cwd=tmp_path
    )
    subprocess.check_call(["git", "tag", "-a", "-m", "release", tag], cwd=tmp_path)
    return Git(tmp_path)


def test_extra_dir_includes_commits_from_extra_directory(
    git_config: None,  # pylint: disable=unused-argument
    tmp_path: Path,
) -> None:
    """Commits touching only an extra-dir should be included in the version bump."""
    git = _init_repo_with_tag(tmp_path, "core/v0.1.0")

    # Commit only touches "shared/" — not the primary "core/" directory
    _commit_file(tmp_path, "shared", "util.py", "feat: add shared utility")

    next_version, _ = _run(git, False, directory="core", extra_dirs=["shared"])
    assert next_version == DEFAULT_FIRST_VERSION.bump_minor()


def test_extra_dir_does_not_affect_tag_scoping(
    git_config: None,  # pylint: disable=unused-argument
    tmp_path: Path,
) -> None:
    """Tags should still be resolved using only the primary directory, not extra dirs."""
    git = _init_repo_with_tag(tmp_path, "core/v0.1.0")

    # Also create a higher-versioned tag scoped to "shared"
    subprocess.check_call(
        ["git", "commit", "--allow-empty", "-m", "bump shared"], cwd=tmp_path
    )
    subprocess.check_call(
        ["git", "tag", "-a", "-m", "release", "shared/v9.0.0"], cwd=tmp_path
    )

    _commit_file(tmp_path, "core", "mod.py", "fix: core bugfix")

    # Even though shared/v9.0.0 exists, tags are scoped to "core" only
    next_version, _ = _run(git, False, directory="core", extra_dirs=["shared"])
    assert next_version == DEFAULT_FIRST_VERSION.bump_patch()


def test_extra_dir_no_commits_raises(
    git_config: None,  # pylint: disable=unused-argument
    tmp_path: Path,
) -> None:
    """If no commits touch primary or extra dirs, should raise ValueError."""
    git = _init_repo_with_tag(tmp_path, "core/v0.1.0")

    _commit_file(tmp_path, "unrelated", "file.py", "feat: unrelated change")

    with pytest.raises(ValueError):
        _run(git, False, directory="core", extra_dirs=["shared"])


def test_extra_dir_combines_with_primary_directory(
    git_config: None,  # pylint: disable=unused-argument
    tmp_path: Path,
) -> None:
    """Commits from both primary and extra dirs are considered together."""
    git = _init_repo_with_tag(tmp_path, "core/v0.1.0")

    _commit_file(tmp_path, "core", "main.py", "fix: core fix")
    _commit_file(tmp_path, "shared", "lib.py", "feat: shared feature")

    # feat is the highest impact, so version should be a minor bump
    next_version, _ = _run(git, False, directory="core", extra_dirs=["shared"])
    assert next_version == DEFAULT_FIRST_VERSION.bump_minor()


def test_extra_dir_multiple_dirs(
    git_config: None,  # pylint: disable=unused-argument
    tmp_path: Path,
) -> None:
    """Multiple extra dirs can be specified."""
    git = _init_repo_with_tag(tmp_path, "core/v0.1.0")

    _commit_file(tmp_path, "lib_b", "mod.py", "feat: lib_b feature")

    next_version, _ = _run(git, False, directory="core", extra_dirs=["lib_a", "lib_b"])
    assert next_version == DEFAULT_FIRST_VERSION.bump_minor()


def test_extra_dir_empty_tuple_behaves_like_no_extra_dirs(
    git_config: None,  # pylint: disable=unused-argument
    tmp_path: Path,
) -> None:
    """Passing an empty extra_dirs tuple should behave the same as not passing it."""
    git = _init_repo_with_tag(tmp_path, "core/v0.1.0")

    _commit_file(tmp_path, "unrelated", "file.py", "feat: unrelated change")

    with pytest.raises(ValueError):
        _run(git, False, directory="core", extra_dirs=())
