#!/usr/bin/env python
"""Tests for flexible task directory structure support.

Tests validation of the new flexible task directory structures without
requiring kubectl or external dependencies.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def disable_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable GitHub Actions mode for all tests by default."""
    monkeypatch.setenv("GITHUB_ACTIONS", "false")


class TestFlexibleTaskStructures:
    """Test that flexible task structures exist and are valid."""

    def test_flexible_structure_examples_exist(self) -> None:
        """Test that all flexible structure examples exist in the repository."""
        expected_structures = [
            "task/nested-example/deep/subdir/nested-example.yaml",
            "task/no-subdirectory/no-subdirectory.yaml",
            "task/no-version-subdirectory/no-version-subdirectory.yaml",
            "task/random-nesting/nesting/nesting-even-deeper/random-nesting.yaml"
        ]

        for structure in expected_structures:
            path = Path.cwd() / structure
            assert path.exists(), f"Expected flexible structure not found: {structure}"
            assert path.is_file(), f"Expected file, found directory: {structure}"

    def test_flexible_task_yaml_files_valid(self) -> None:
        """Test that flexible structure YAML files are valid Tekton tasks."""
        import yaml

        task_files = [
            "task/nested-example/deep/subdir/nested-example.yaml",
            "task/no-subdirectory/no-subdirectory.yaml",
            "task/no-version-subdirectory/no-version-subdirectory.yaml",
            "task/random-nesting/nesting/nesting-even-deeper/random-nesting.yaml"
        ]

        for task_file in task_files:
            path = Path.cwd() / task_file
            if not path.exists():
                continue

            # Parse YAML and validate basic structure
            with open(path) as f:
                content = yaml.safe_load(f)

            assert content.get("apiVersion") == "tekton.dev/v1"
            assert content.get("kind") == "Task"
            assert "metadata" in content
            assert "name" in content["metadata"]

            # Check for version metadata
            labels = content["metadata"].get("labels", {})
            assert "app.kubernetes.io/version" in labels, f"Missing version label in {task_file}"

    def test_task_names_match_directory_structure(self) -> None:
        """Test that task names align with directory structure expectations."""
        test_cases = [
            ("task/nested-example/deep/subdir/nested-example.yaml", "nested-example"),
            ("task/no-subdirectory/no-subdirectory.yaml", "no-subdirectory"),
            ("task/random-nesting/nesting/nesting-even-deeper/random-nesting.yaml", "random-nesting")
        ]

        import yaml

        for task_file, expected_name in test_cases:
            path = Path.cwd() / task_file
            if not path.exists():
                continue

            with open(path) as f:
                content = yaml.safe_load(f)

            actual_name = content["metadata"]["name"]
            assert actual_name == expected_name, f"Task name mismatch in {task_file}: expected {expected_name}, got {actual_name}"


class TestShellScriptSyntax:
    """Test that shell scripts have valid syntax and basic functionality."""

    def test_shell_scripts_syntax(self) -> None:
        """Test that modified shell scripts have valid syntax."""
        scripts = [
            ".github/scripts/check_tekton_tasks.sh",
            ".github/scripts/test_tekton_tasks.sh",
            "hack/build-manifests.sh",
            "hack/create-task-migration.sh",
            "hack/missing-ta-tasks.sh",
            "hack/validate-migration.sh"
        ]

        for script in scripts:
            script_path = Path.cwd() / script
            if not script_path.exists():
                continue

            result = subprocess.run(
                ["/bin/bash", "-n", str(script_path)],
                capture_output=True,
                text=True
            )

            assert result.returncode == 0, f"Syntax error in {script}: {result.stderr}"

    def test_check_tekton_tasks_no_arguments(self) -> None:
        """Test check_tekton_tasks.sh with no arguments (no kubectl needed)."""
        script_path = Path.cwd() / ".github/scripts/check_tekton_tasks.sh"

        result = subprocess.run(
            ["/bin/bash", str(script_path)],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "No changed task directories provided, nothing to validate" in result.stdout

    def test_test_tekton_tasks_help(self) -> None:
        """Test test_tekton_tasks.sh help option (no kubectl needed)."""
        script_path = Path.cwd() / ".github/scripts/test_tekton_tasks.sh"

        result = subprocess.run(
            ["/bin/bash", str(script_path), "-h"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 1  # Help exits with error code
        assert "Usage:" in result.stdout


class TestDocumentationConsistency:
    """Test that documentation reflects the flexible structure changes."""

    def test_shared_ci_documentation_updated(self) -> None:
        """Test that SHARED-CI.md mentions flexible structures."""
        shared_ci_path = Path.cwd() / "SHARED-CI.md"
        if not shared_ci_path.exists():
            pytest.skip("SHARED-CI.md not found")

        content = shared_ci_path.read_text()

        # Should mention flexible structure support
        assert "flexible" in content.lower() or "nested" in content.lower(), \
            "SHARED-CI.md should document flexible structure support"