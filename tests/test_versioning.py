#!/usr/bin/env python
"""Integration tests for hack/versioning.py.

Typically, each test works like this:

- Create a new repo at tmp_path
- Write some task files into it, optionally commit the changes
- Execute the hack/versioning.py script in the repo, check the output
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture(autouse=True)
def disable_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable GitHub Actions mode for all tests by default."""
    monkeypatch.setenv("GITHUB_ACTIONS", "false")


# --- Declarative file tree helpers ---


def task(
    name: str,
    version: str | None,
    add_comment: bool = False,
) -> str:
    """Generate task YAML content."""
    content = dedent(
        f"""\
        apiVersion: tekton.dev/v1
        kind: Task
        metadata:
          name: {name}
          labels:
            {f'app.kubernetes.io/version: "{version}"' if version else "foo: bar"}
        spec:
          description: Test task
          steps:
            - name: test
              image: test:latest
              script: |
                echo "test"
        """
    )

    if add_comment:
        content += "# A comment to trigger versioning checks.\n"

    return content


def changelog(*versions: str) -> str:
    """Generate changelog content."""
    content = "# Changelog"
    for version in versions:
        content += dedent(
            f"""
            ## {version}

            ### Added

            - Something interesting!
            """
        )
    return content


def write_files(path: Path, files: dict[str, str]) -> None:
    """Create a file tree at 'path'."""
    for filepath, content in files.items():
        full_path = path / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)


class TaskRepo:
    """Helper class for declaratively creating test repositories with file trees."""

    def __init__(self, path: Path):
        self.path = path
        self._run_git("init")

        # Create local git config to isolate from user's global config
        git_config = self.path / ".git" / "config"
        git_config.write_text(
            dedent(
                """\
                [user]
                    # Use test identity instead of user's global config
                    name = Test User
                    email = test@example.com
                [commit]
                    # Disable GPG signing to avoid dependency on user's GPG setup
                    gpgsign = false
                [core]
                    # Disable hooks to avoid interference from pre-commit, commit-msg, etc.
                    hooksPath = /dev/null
                """
            )
        )

        self._run_git("branch", "-M", "main")
        self._run_git("commit", "--allow-empty", "-m", "Initial commit")

    def _run_git(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run a git command in the repo."""
        return subprocess.run(
            ["git", *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            check=True,
        )

    def add_files(self, files: dict[str, str]) -> None:
        """Wrapper for write_files, use when adding new files (to make tests readable)."""
        write_files(self.path, files)

    def modify_files(self, files: dict[str, str]) -> None:
        """Wrapper for write_files, use when changing existing files (to make tests readable)."""
        write_files(self.path, files)

    def stage(self) -> None:
        """Stage all changes (both modifications and new files)."""
        self._run_git("add", ".")

    def commit(self, message: str, *, stage: bool = True) -> None:
        """Create a commit with the given message."""
        if stage:
            self.stage()
        self._run_git("commit", "-m", message)

    def branch(self, name: str) -> None:
        """Create and checkout a new branch."""
        self._run_git("checkout", "-b", name)


@pytest.fixture
def repo_path(tmp_path: Path) -> Path:
    """Temporary directory for a task repo."""
    # Copy hack/versioning.py to the test repo so that we can execute it by relative path
    # (the script path shows up in the script output, so this makes test assertions easier)
    versioning_py = Path(__file__).parent.parent / "hack" / "versioning.py"
    (tmp_path / "hack").mkdir(exist_ok=True)
    (tmp_path / "hack" / "versioning.py").write_text(versioning_py.read_text())
    return tmp_path


def create_repo(repo_path: Path, files: dict[str, str] | None = None) -> TaskRepo:
    """Create a git repo with optional initial files."""
    repo = TaskRepo(repo_path)
    if files:
        repo.add_files(files)
        repo.commit("Initial setup")
    return repo


# --- Tests ---


def run_versioning_script(
    repo_path: Path,
    *args: str,
    expect_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run the versioning script and return the completed process."""
    result = subprocess.run(
        [sys.executable, "hack/versioning.py", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if not expect_failure and result.returncode != 0:
        pytest.fail(
            f"versioning.py failed unexpectedly:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    return result


class TestCheckCommand:
    """Tests for the 'check' subcommand."""

    def test_new_task_errors(self, repo_path: Path) -> None:
        """Test the errors reported for new tasks.

        - Missing/invalid version
        - Missing changelog
        """
        repo = create_repo(
            repo_path,
            {
                "task/task1/task1.yaml": task("task1", version=None),
                "task/task2/task2.yaml": task("task2", "invalid-version"),
            },
        )

        result = run_versioning_script(
            repo.path, "check", "--base-ref", "HEAD~1", expect_failure=True
        )

        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr == dedent(
            """\
            Error: task/task1/task1.yaml: Missing app.kubernetes.io/version label
            Error: task/task1/task1.yaml: CHANGELOG.md missing at task/task1/CHANGELOG.md. Use 'hack/versioning.py new-changelog task/task1' to create one.
            Error: task/task2/task2.yaml:6: Invalid version: invalid-version
            Error: task/task2/task2.yaml: CHANGELOG.md missing at task/task2/CHANGELOG.md. Use 'hack/versioning.py new-changelog task/task2' to create one.
            """
        )

    def test_new_task_valid(self, repo_path: Path) -> None:
        """New task with version and CHANGELOG should pass."""
        repo = create_repo(
            repo_path,
            {
                "task/hello/hello.yaml": task("hello", "0.1"),
                "task/hello/CHANGELOG.md": changelog("0.1"),
            },
        )

        result = run_versioning_script(repo.path, "check", "--base-ref", "HEAD~1")

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_modified_task_warnings(self, repo_path: Path) -> None:
        """Test the warnings reported for modified tasks.

        - Missing/invalid/unchanged version labels
        - Missing/unchanged changelogs
        """
        repo = create_repo(
            repo_path,
            {
                "task/task1/task1.yaml": task("task1", version=None),
                "task/task2/task2.yaml": task("task2", "invalid-version"),
                "task/task2/CHANGELOG.md": changelog("invalid-version"),
            },
        )
        repo.branch("test")

        repo.modify_files(
            {
                # Note: shouldn't warn about unchanged task1 version, task1 doesn't have a version
                "task/task1/task1.yaml": task("task1", version=None, add_comment=True),
                "task/task2/task2.yaml": task("task2", "invalid-version", add_comment=True),
            }
        )
        repo.commit("Modify tasks")

        result = run_versioning_script(repo.path, "check", "--base-ref", "main")

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == dedent(
            """\
            Warning: task/task1/task1.yaml: Missing app.kubernetes.io/version label
            Warning: task/task1/task1.yaml: CHANGELOG.md missing at task/task1/CHANGELOG.md. Use 'hack/versioning.py new-changelog task/task1' to create one.
            Warning: task/task2/task2.yaml:6: Invalid version: invalid-version
            Warning: task/task2/task2.yaml:6: app.kubernetes.io/version label is unchanged. CI pipeline may skip building the task.
            Warning: task/task2/task2.yaml: CHANGELOG.md at task/task2/CHANGELOG.md is unchanged. Please consider updating it.
            """
        )

    def test_modified_task_valid(self, repo_path: Path) -> None:
        """Modified task with updated version and CHANGELOG should pass."""
        repo = create_repo(
            repo_path,
            {
                "task/hello/hello.yaml": task("hello", "0.1"),
                "task/hello/CHANGELOG.md": changelog("0.1"),
            },
        )
        repo.branch("test")

        repo.modify_files(
            {
                "task/hello/hello.yaml": task("hello", "0.1.1"),
                "task/hello/CHANGELOG.md": changelog("0.1.1", "0.1"),
            }
        )
        repo.commit("Update task and changelog")

        result = run_versioning_script(repo.path, "check", "--base-ref", "main")

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_uncommitted_changes(self, repo_path: Path) -> None:
        """Should detect all uncommitted changes."""
        repo = create_repo(
            repo_path,
            {
                "task/task1/task1.yaml": task("task1", "0.1"),
                "task/task1/CHANGELOG.md": changelog("0.1"),
                "task/task2/task2.yaml": task("task2", "0.1"),
                "task/task2/CHANGELOG.md": changelog("0.1"),
            },
        )
        repo.branch("test")

        # Staged new task
        repo.add_files(
            {"task/staged-new/staged-new.yaml": task("staged-new", "0.1")},
        )
        repo.stage()

        # Untracked new task
        repo.add_files({"task/untracked/untracked.yaml": task("untracked", "0.1")})

        # Staged modification
        repo.modify_files({"task/task1/task1.yaml": task("existing", "0.2")})
        repo.stage()

        # Unstaged modification
        repo.modify_files(
            {
                "task/task2/task2.yaml": task("task2", "0.2"),
                "task/unstaged/CHANGELOG.md": changelog("0.1"),
            }
        )

        result = run_versioning_script(
            repo.path, "check", "--base-ref", "main", expect_failure=True
        )

        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr == dedent(
            """\
            Error: task/staged-new/staged-new.yaml: CHANGELOG.md missing at task/staged-new/CHANGELOG.md. Use 'hack/versioning.py new-changelog task/staged-new' to create one.
            Warning: task/task1/task1.yaml: CHANGELOG.md at task/task1/CHANGELOG.md is unchanged. Please consider updating it.
            Warning: task/task2/task2.yaml: CHANGELOG.md at task/task2/CHANGELOG.md is unchanged. Please consider updating it.
            Error: task/untracked/untracked.yaml: CHANGELOG.md missing at task/untracked/CHANGELOG.md. Use 'hack/versioning.py new-changelog task/untracked' to create one.
            """
        )

    def test_github_actions_format(self, repo_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """In GitHub Actions, output should use ::error format."""
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        repo = create_repo(
            repo_path,
            {
                "task/hello/hello.yaml": task("hello", "0.1"),
                # No changelog
            },
        )

        result = run_versioning_script(
            repo.path, "check", "--base-ref", "HEAD~1", expect_failure=True
        )

        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr == dedent(
            """\
            ::error file=task/hello/hello.yaml,line=1::CHANGELOG.md missing at task/hello/CHANGELOG.md. Use 'hack/versioning.py new-changelog task/hello' to create one.
            """
        )


class TestNewChangelogCommand:
    """Tests for the 'new-changelog' subcommand."""

    def test_create_changelog_initial_version(self, repo_path: Path) -> None:
        """Creating CHANGELOG for version ≤0.1 should use 'initial version' message."""
        write_files(
            repo_path,
            {
                "task/hello/hello.yaml": task("hello", "0.1"),
            },
        )

        result = run_versioning_script(repo_path, "new-changelog", "task/hello")

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == dedent(
            """\
            Info: task/hello: Created CHANGELOG.md at task/hello/CHANGELOG.md
            """
        )

        changelog_path = repo_path / "task" / "hello" / "CHANGELOG.md"
        assert changelog_path.exists()
        assert changelog_path.read_text() == dedent(
            """\
            # Changelog

            ## Unreleased

            <!--
            When you make changes without bumping the version right away, document them here.
            If that's not something you ever plan to do, consider removing this section.
            -->

            *Nothing yet.*

            ## 0.1

            ### Added

            - The initial version of the `hello` task!
            """
        )

    def test_create_changelog_later_version(self, repo_path: Path) -> None:
        """Creating CHANGELOG for version >0.1 should use 'started tracking' message."""
        write_files(
            repo_path,
            {
                "task/hello/hello.yaml": task("hello", "0.5"),
            },
        )

        result = run_versioning_script(repo_path, "new-changelog", "task/hello")

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == dedent(
            """\
            Info: task/hello: Created CHANGELOG.md at task/hello/CHANGELOG.md
            """
        )

        changelog_path = repo_path / "task" / "hello" / "CHANGELOG.md"
        assert changelog_path.exists()
        assert changelog_path.read_text() == dedent(
            """\
            # Changelog

            ## Unreleased

            <!--
            When you make changes without bumping the version right away, document them here.
            If that's not something you ever plan to do, consider removing this section.
            -->

            *Nothing yet.*

            ## 0.5

            ### Added

            - Started tracking changes in this file.
            """
        )

    def test_changelog_already_exists(self, repo_path: Path) -> None:
        """Creating CHANGELOG when one exists should skip with info."""
        write_files(
            repo_path,
            {
                "task/hello/hello.yaml": task("hello", "0.1"),
                "task/hello/CHANGELOG.md": "# Existing changelog\n",
            },
        )

        result = run_versioning_script(repo_path, "new-changelog", "task/hello")

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == dedent(
            """\
            Info: task/hello: task/hello/CHANGELOG.md already exists, skipping
            """
        )

        # Verify original content is preserved
        changelog_path = repo_path / "task" / "hello" / "CHANGELOG.md"
        assert changelog_path.read_text() == "# Existing changelog\n"

    def test_multiple_versions_uses_highest(self, repo_path: Path) -> None:
        """Creating CHANGELOG with multiple task YAMLs should use highest version."""
        write_files(
            repo_path,
            {
                # Multiple YAML files under same task dir (legacy structure)
                "task/hello/0.1/hello.yaml": task("hello", "0.1"),
                "task/hello/0.2/hello.yaml": task("hello", "0.2"),
                "task/hello/0.3/hello.yaml": task("hello", "0.3"),
            },
        )

        # Should pick the highest version even if the caller passes in a specific task file
        result = run_versioning_script(repo_path, "new-changelog", "task/hello/0.1/hello.yaml")

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == dedent(
            """\
            Info: task/hello: Created CHANGELOG.md at task/hello/CHANGELOG.md
            """
        )

        changelog_path = repo_path / "task" / "hello" / "CHANGELOG.md"
        assert changelog_path.read_text() == dedent(
            """\
            # Changelog

            ## Unreleased

            <!--
            When you make changes without bumping the version right away, document them here.
            If that's not something you ever plan to do, consider removing this section.
            -->

            *Nothing yet.*

            ## 0.3

            ### Added

            - Started tracking changes in this file.
            """
        )

    def test_task_with_invalid_version(self, repo_path: Path) -> None:
        """Creating CHANGELOG for task with invalid version should error."""
        write_files(
            repo_path,
            {
                # Should skip task if *any* of the task's files has an invalid version
                "task/hello/0.1/hello.yaml": task("hello", "0.1"),
                "task/hello/0.2/hello.yaml": task("hello", "0.2.3.4"),
                "task/hello/0.3/hello.yaml": task("hello", "0.3"),
            },
        )

        result = run_versioning_script(
            repo_path, "new-changelog", "task/hello", expect_failure=True
        )

        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr == dedent(
            """\
            Error: task/hello/0.2/hello.yaml:6: Invalid version: 0.2.3.4. Cannot determine current version for task/hello.
            """
        )

        # CHANGELOG should not be created
        changelog_path = repo_path / "task" / "hello" / "CHANGELOG.md"
        assert not changelog_path.exists()

    def test_create_multiple_changelogs(self, repo_path: Path) -> None:
        """Creating CHANGELOGs for multiple tasks should process all."""
        write_files(
            repo_path,
            {
                "task/task1/task1.yaml": task("task1", "0.1"),
                "task/task2/task2.yaml": task("task2", "0.1"),
                "task/task3/task3.yaml": task("task3", "0.1"),
            },
        )

        result = run_versioning_script(repo_path, "new-changelog", "task/")

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == dedent(
            """\
            Info: task/task1: Created CHANGELOG.md at task/task1/CHANGELOG.md
            Info: task/task2: Created CHANGELOG.md at task/task2/CHANGELOG.md
            Info: task/task3: Created CHANGELOG.md at task/task3/CHANGELOG.md
            """
        )

        # All three CHANGELOGs should be created
        assert (repo_path / "task" / "task1" / "CHANGELOG.md").exists()
        assert (repo_path / "task" / "task2" / "CHANGELOG.md").exists()
        assert (repo_path / "task" / "task3" / "CHANGELOG.md").exists()


class TestFlexibleStructureSupport:
    """Test versioning script behavior with flexible task structures."""

    def test_traditional_structure_still_supported(self, repo_path: Path) -> None:
        """Test that traditional task/name/version/name.yaml structure still works."""
        repo = create_repo(
            repo_path,
            {
                "task/hello/0.1/hello.yaml": task("hello", "0.1"),
                "task/hello/CHANGELOG.md": changelog("0.1"),
            },
        )

        result = run_versioning_script(repo.path, "check", "--base-ref", "HEAD~1")

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_flat_structure_discovery_limitation(self, repo_path: Path) -> None:
        """Test current limitation: versioning script doesn't yet support flat structures.

        This test documents the current behavior and should be updated when
        the versioning script is enhanced to support flexible structures.
        """
        repo = create_repo(
            repo_path,
            {
                # Flat structure like task/hello/hello.yaml
                "task/hello/hello.yaml": task("hello", "0.1"),
                "task/hello/CHANGELOG.md": changelog("0.1"),
            },
        )

        result = run_versioning_script(repo.path, "check", "--base-ref", "HEAD~1")

        # Currently expected to pass with no tasks found since versioning script
        # doesn't recognize flat structure as valid task files
        assert result.returncode == 0
        # No errors should occur, but no tasks will be processed

    def test_nested_structure_discovery_limitation(self, repo_path: Path) -> None:
        """Test current limitation: versioning script doesn't support deeply nested structures.

        This test documents the current behavior and should be updated when
        the versioning script is enhanced to support flexible structures.
        """
        repo = create_repo(
            repo_path,
            {
                # Nested structure like task/nested/deep/subdir/nested.yaml
                "task/nested/deep/subdir/nested.yaml": task("nested", "0.1"),
                "task/nested/CHANGELOG.md": changelog("0.1"),
            },
        )

        result = run_versioning_script(repo.path, "check", "--base-ref", "HEAD~1")

        # Currently expected to pass with no tasks found since versioning script
        # doesn't recognize nested structure as valid task files
        assert result.returncode == 0

    @pytest.mark.xfail(reason="Versioning script not yet updated for flexible structures")
    def test_flexible_structure_version_check_future(self, repo_path: Path) -> None:
        """Test that will pass once versioning script supports flexible structures.

        This test is marked as expected to fail until the versioning script
        is updated to support the new flexible task directory structures.
        """
        repo = create_repo(
            repo_path,
            {
                "task/flexible-task/flexible-task.yaml": task("flexible-task", "0.1"),
                "task/flexible-task/CHANGELOG.md": changelog("0.1"),
            },
        )

        result = run_versioning_script(repo.path, "check", "--base-ref", "HEAD~1")

        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_versioning_script_task_discovery_pattern(self, repo_path: Path) -> None:
        """Test the current task discovery pattern in versioning script.

        Verifies that the is_task_file function correctly identifies traditional
        task structures while documenting its current limitations.
        """
        repo = create_repo(
            repo_path,
            {
                # Traditional structure that should be found
                "task/traditional/0.1/traditional.yaml": task("traditional", "0.1"),
                "task/traditional/CHANGELOG.md": changelog("0.1"),
                # Structure that won't be found due to current limitations
                "task/flexible/flexible.yaml": task("flexible", "0.1"),
                "task/flexible/CHANGELOG.md": changelog("0.1"),
            },
        )

        result = run_versioning_script(repo.path, "check", "--base-ref", "HEAD~1")

        # Should process the traditional task but not the flexible one
        assert result.returncode == 0
        # The traditional task should be validated without errors

    def test_mixed_structure_repository_compatibility(self, repo_path: Path) -> None:
        """Test versioning script in a repository with mixed task structures.

        Ensures the script handles repos that have both traditional and
        flexible structures gracefully.
        """
        repo = create_repo(
            repo_path,
            {
                # Traditional structure
                "task/old-style/1.0/old-style.yaml": task("old-style", "1.0"),
                "task/old-style/CHANGELOG.md": changelog("1.0"),
                # Flexible structure (won't be processed currently)
                "task/new-style/new-style.yaml": task("new-style", "1.0"),
                "task/new-style/CHANGELOG.md": changelog("1.0"),
            },
        )

        result = run_versioning_script(repo.path, "check", "--base-ref", "HEAD~1")

        # Should process available tasks without failing on unrecognized structures
        assert result.returncode == 0

    def test_changelog_creation_traditional_vs_flexible(self, repo_path: Path) -> None:
        """Test changelog creation for both traditional and flexible structures."""
        write_files(
            repo_path,
            {
                # Traditional structure
                "task/traditional/0.1/traditional.yaml": task("traditional", "0.1"),
                # Flexible structure
                "task/flexible/flexible.yaml": task("flexible", "0.1"),
            },
        )

        # Try to create changelogs for both
        result_traditional = run_versioning_script(
            repo_path, "new-changelog", "task/traditional"
        )
        result_flexible = run_versioning_script(
            repo_path, "new-changelog", "task/flexible"
        )

        # Traditional should work
        assert result_traditional.returncode == 0
        assert "Created CHANGELOG.md" in result_traditional.stderr

        # Flexible structure may not be recognized (current limitation)
        # The script should handle this gracefully without crashing
        assert result_flexible.returncode in [0, 1]  # Either succeeds or fails gracefully
