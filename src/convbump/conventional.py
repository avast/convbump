from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Collection, Dict, Iterable, List, Optional, Tuple

from .git import Commit

logger = logging.getLogger(__name__)

BREAKING_CHANGE_IN_BODY = "BREAKING CHANGE:"


class VersionImpact(Enum):
    """Represents the impact a commit has on semantic versioning."""

    MAJOR = 3  # Breaking changes
    MINOR = 2  # New features
    PATCH = 1  # Bug fixes, improvements, etc.
    NONE = 0  # No version impact


def get_commit_version_impact(commit_type: str, is_breaking: bool) -> VersionImpact:
    """
    Determine the version impact of a commit based on semantic versioning rules.
    This is the single source of truth for version impact logic.
    """
    if is_breaking:
        return VersionImpact.MAJOR
    elif commit_type.lower() == "feat":
        return VersionImpact.MINOR
    else:
        return VersionImpact.PATCH


SUBJECT_REGEX = re.compile(
    r"""^
        (?:                         # Non-matchin group with commit type and optional scope
            (?P<type>[a-zA-Z]*?)    # Commit type (named group)
            (?:
                \(                  # Literal (
                    (?P<scope>.*)   # Scope (named group)
                \)                  # Literal )
            )?
        )
        (?P<breaking>!)?            # Breaking change mark (named group)
        :\s?                        # ':' follwed by any number of whitespace
        (?P<subject>.*)             # Rest of the subejct(named group)
        $
    """,
    re.VERBOSE,
)


class CommitType(Enum):
    FEAT = "feat"
    FIX = "fix"
    CHORE = "chore"
    DOCS = "docs"
    TEST = "test"
    REFACTOR = "refactor"
    STYLE = "style"
    BUILD = "build"
    CI = "ci"
    OTHER = "other"


def parse_subject(subject: str) -> Tuple[str, Optional[str], bool, str]:
    match = SUBJECT_REGEX.match(subject)
    if match:
        matched_dict = match.groupdict()
        if not matched_dict["subject"]:
            raise ValueError(f"Invalid conventional commit subject: {subject}")

        commit_type = matched_dict["type"]
        is_breaking = bool(matched_dict.get("breaking", None))

        return (commit_type, matched_dict.get("scope"), is_breaking, matched_dict["subject"])
    else:
        raise ValueError(f"Invalid conventional commit subject: {subject}")


def should_ignore(message: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if pattern and pattern in message:
            logger.debug(
                f"Ignoring commit message: {message} because it matches pattern {pattern}"
            )
            return True
    return False


def find_conventional_commit_in_body(
    body: str, ignored_patterns: Optional[Iterable[str]] = None
) -> Optional[Tuple[str, Optional[str], bool, str]]:
    """
    Search for conventional commit patterns in the body text, respecting newlines.
    Returns the highest priority conventional commit found, or None if none found.
    Priority order: feat! > feat > fix > perf/refactor > others

    If ignored_patterns is provided, commits matching those patterns will be excluded.
    """
    if not body:
        return None

    if ignored_patterns is None:
        ignored_patterns = []

    # Split body into lines and search each line
    lines = body.split("\n")

    found_commits = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Remove common prefixes like "* ", "- ", "• ", etc.
        # This handles bullet points in squashed merge commits
        cleaned_line = re.sub(r"^[\*\-\•]\s*", "", line)

        try:
            # Try to parse this cleaned line as a conventional commit subject
            commit_info = parse_subject(cleaned_line)
            commit_type, _, is_breaking, _ = commit_info

            # Check if this individual commit should be ignored
            if should_ignore(cleaned_line, ignored_patterns):
                continue

            impact = get_commit_version_impact(commit_type, is_breaking)
            found_commits.append((impact.value, commit_info))
        except ValueError:
            # This line is not a conventional commit, continue to next line
            continue

    if not found_commits:
        return None

    # Return the commit with highest priority
    found_commits.sort(key=lambda x: x[0], reverse=True)
    return found_commits[0][1]


@dataclass(frozen=True)
class ConventionalCommit:

    commit_type: CommitType
    scope: Optional[str]
    is_breaking: bool
    subject: str
    body: Optional[str]
    hash: str
    raw_subject: str
    is_conventional: bool = True  # Whether this was parsed as a conventional commit
    parsed_from_body: bool = False  # Whether this was parsed from body (squashed commit)

    @classmethod
    def from_git_commit(
        cls, git_commit: Commit, ignored_patterns: Optional[Iterable[str]] = None
    ) -> ConventionalCommit:
        is_conventional = False
        parsed_from_body = False

        # Try to parse the subject first
        try:
            raw_commit_type, scope, is_breaking, subject = parse_subject(git_commit.subject)
            is_conventional = True
        except ValueError:
            # Subject is not a conventional commit, try to find one in the body
            body_result = (
                find_conventional_commit_in_body(git_commit.body, ignored_patterns)
                if git_commit.body
                else None
            )
            if body_result is not None:
                raw_commit_type, scope, is_breaking, subject = body_result
                is_conventional = True
                parsed_from_body = True
            else:
                # Neither subject nor body contains conventional commit format
                # Treat as OTHER type commit with original subject
                raw_commit_type = "other"
                scope = None
                is_breaking = False
                subject = git_commit.subject
                is_conventional = False

        try:
            commit_type = CommitType[raw_commit_type.upper()]
        except KeyError:
            commit_type = CommitType.OTHER

        # Check for breaking change in body regardless of where we parsed from
        if git_commit.body is not None and BREAKING_CHANGE_IN_BODY in git_commit.body:
            is_breaking = True

        return cls(
            commit_type=commit_type,
            scope=scope,
            is_breaking=is_breaking,
            subject=subject,
            body=git_commit.body or None,
            hash=git_commit.hash.decode()[:7],
            raw_subject=git_commit.subject,
            is_conventional=is_conventional,
            parsed_from_body=parsed_from_body,
        )

    def format(self) -> str:

        if self.scope:
            scope = f"(`{self.scope}`)"
        else:
            scope = ""

        if self.commit_type not in (CommitType.FEAT, CommitType.FIX):
            commit_type = f"{self.commit_type.value}{scope}: "
        else:
            if scope:
                commit_type = f"{scope} "
            else:
                commit_type = ""

        if self.is_breaking:
            breaking = "**BREAKING CHANGE** "
        else:
            breaking = ""

        return f"{breaking}{commit_type}{self.subject} ({self.hash})"


def format_changelog(commits: Collection[ConventionalCommit]) -> str:
    """Return a formatted changelog in Markdown format. Feature and fix commits
    are listed in a separate sections. Other commit types are grouped together
    in "Other" section."""

    commit_groups: Dict[CommitType, List[ConventionalCommit]] = defaultdict(list)

    for commit in commits:
        if commit.commit_type in (CommitType.FEAT, CommitType.FIX):
            commit_type = commit.commit_type
        else:
            commit_type = CommitType.OTHER

        commit_groups[commit_type].append(commit)

    lines = []

    for commit_type in CommitType:
        if commit_type in commit_groups:
            if commit_type == CommitType.FEAT:
                title = "Features"
            elif commit_type == CommitType.FIX:
                title = "Fixes"
            else:
                title = "Other"

            lines.append(f"\n### {title}")
            for commit in commit_groups[commit_type]:
                lines.append(f"* {commit.format()}")

    return "\n".join(lines).strip()
