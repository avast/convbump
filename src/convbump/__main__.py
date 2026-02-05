import logging
import sys
from pathlib import Path
from typing import Iterable, Optional, Tuple

import click
from semver import VersionInfo as Version

from .conventional import ConventionalCommit, format_changelog, should_ignore
from .git import Git
from .version import DEFAULT_FIRST_VERSION, get_next_version

logger = logging.getLogger(__name__)


def echo(*values: str) -> None:
    print(*values, file=sys.stderr)


def ignore_commit(patterns: Iterable[str], commit: ConventionalCommit) -> bool:
    """Check if any pattern is contained in the commit subject.

    For regular commits (conventional commit in subject), we only check the subject
    because the body may contain squashed commit messages that shouldn't affect
    the ignore logic.
    """
    return should_ignore(commit.raw_subject, patterns)


def _run(
    git: Git,
    strict: bool,
    directory: Optional[str] = None,
    ignored_patterns: Optional[Iterable[str]] = None,
) -> Tuple[Version, str]:
    """Find the next version and generate a changelog from
    conventional commits.

    If `strict` is True, non-conventional commits are not allowed and the command will fail.

    If `directory` is not None, only commits that affect that directory  and tags
    containing this directory (normalized) are selected."""

    if ignored_patterns is None:
        ignored_patterns = []

    tag, current_version = git.retrieve_last_version(directory)
    logger.debug("Latest tag=%s on current_version=%s", tag, current_version)
    if not current_version:
        echo("Using default first version")
        return DEFAULT_FIRST_VERSION, ""

    conventional_commits = []
    for commit in git.list_commits(tag):
        if not directory or commit.affects_dir(directory):
            conventional_commit = ConventionalCommit.from_git_commit(commit, ignored_patterns)
            logger.debug("Processed conventional_commit=%s", conventional_commit)
            # Check if this is a non-conventional commit in strict mode
            if not conventional_commit.is_conventional and strict:
                raise ValueError(f"Non-conventional commit found in strict mode: {commit.subject}")

            # Only include conventional commits for version calculation
            if conventional_commit.is_conventional:
                if conventional_commit.parsed_from_body:
                    # This is a squashed commit - ignore filtering was already applied during body parsing
                    conventional_commits.append(conventional_commit)
                else:
                    # This is a regular commit - apply ignore patterns
                    if not ignore_commit(ignored_patterns, conventional_commit):
                        conventional_commits.append(conventional_commit)

    if len(conventional_commits) == 0:
        raise ValueError("No commits found after the latest tag")

    next_version = get_next_version(current_version, conventional_commits)
    changelog = format_changelog(conventional_commits)

    return next_version, changelog


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Show debug logs.")
def convbump(verbose: bool) -> None:
    """convbump is a simple tool to work with conventional commits.

    Use the `version` command to find the next version in your repository
    based on the conventional commits.

    Use the `changelog` command to generate a nicely formatted changelog
    (Github markdown compatible).

    Args:
        verbose: If true, shows debug logs.
    """
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)


@convbump.command()
@click.pass_context
@click.option(
    "--project-path", default=".", type=click.Path(file_okay=False, exists=True, path_type=Path)
)
@click.option(
    "--strict", is_flag=True, default=False, help="Fail if non-Conventinal commits are found"
)
@click.option(
    "--ignore-pattern",
    is_flag=False,
    multiple=True,
    help="Commits with containing this pattern will be ignored",
)
@click.argument("directory", required=False)
def version(
    ctx: click.Context,
    project_path: Path,
    strict: bool,
    ignore_pattern: Tuple[str],
    directory: Optional[str],
) -> None:
    """Calculate next version from Git history.

    Given a Git repository, this command will find the latest version tag and
    calculate the next version using the Conventional Commits (CC) specification.

    Optional argument DIRECTORY controls which tags and CCs should be considered (all by default).
    Use this argument in mono-repos. Only tags and commits affecting DIRECTORY will be selected.

    Calculated version will be printed out to STDOUT.

    By default non-CC commits are allowed. Use the `--strict` flag to fail
    if any non-CC commits are present."""

    git = Git(project_path)

    try:
        next_version, changelog = _run(git, strict, directory, ignore_pattern)
    except ValueError as e:
        ctx.fail(e)  # type: ignore

    echo("Changes:")
    echo(changelog)
    echo("\nNext version:")
    print(next_version)


@convbump.command()
@click.pass_context
@click.option(
    "--project-path", default=".", type=click.Path(file_okay=False, exists=True, path_type=Path)
)
@click.option(
    "--strict", is_flag=True, default=False, help="Fail if non-Conventinal commits are found"
)
@click.option(
    "--ignore-pattern",
    is_flag=False,
    multiple=True,
    help="Commits with containing this pattern will be ignored",
)
@click.argument("directory", required=False)
def changelog(
    ctx: click.Context,
    project_path: Path,
    strict: bool,
    ignore_pattern: Tuple[str],
    directory: Optional[str],
) -> None:
    """Create a ChangeLog from Git history.

    Given a Git repository, this command will find the latest version tag and
    generate a ChangeLog from Conventional Commits (CC).

    Optional argument DIRECTORY controls which tags and CCs should be considered (all by default).
    Use this argument in mono-repos. Only tags and commits affecting DIRECTORY will be selected.

    Generated ChangeLog will be printed out to STDOUT.

    By default non-CC commits are allowed. Use the `--strict` flag to fail
    if any non-CC commits are present."""

    git = Git(project_path)

    try:
        next_version, changelog = _run(git, strict, directory, ignore_pattern)
    except ValueError as e:
        ctx.fail(e)  # type: ignore

    echo("Next version:", str(next_version))
    echo("\nChanges:")
    print(changelog)


if __name__ == "__main__":
    convbump()
