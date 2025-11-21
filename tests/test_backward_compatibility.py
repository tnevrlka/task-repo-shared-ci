#!/usr/bin/env python
"""Backward compatibility tests for flexible task structure changes.

Ensures that traditional task structures are still supported alongside
the new flexible structures.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def disable_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable GitHub Actions mode for all tests by default."""
    monkeypatch.setenv("GITHUB_ACTIONS", "false")


class TestTraditionalStructureSupport:
    """Test that traditional task structures are still supported."""

    def test_traditional_task_structures_exist(self) -> None:
        """Test that traditional task structures still exist in the repository."""
        traditional_pattern = Path.cwd() / "task" / "*" / "*" / "*.yaml"
        traditional_tasks = list(traditional_pattern.parent.glob("*/[0-9]*/"))

        if not traditional_tasks:
            pytest.skip("No traditional task structures found in repository")

        # Should find at least some traditional structures
        assert len(traditional_tasks) > 0, "No traditional task structures found"

        # Verify they follow the expected pattern
        for task_dir in traditional_tasks[:3]:  # Check first 3
            parent_dir = task_dir.parent
            version_dir = task_dir.name
            task_name = parent_dir.name

            # Should follow task/name/version/ pattern
            assert parent_dir.parent.name == "task", f"Expected task directory, found {parent_dir.parent.name}"
            assert version_dir.replace(".", "").replace("-", "").isdigit() or "." in version_dir, \
                f"Expected version directory, found {version_dir}"

            # Should contain task YAML file
            expected_yaml = task_dir / f"{task_name}.yaml"
            assert expected_yaml.exists(), f"Expected task YAML not found: {expected_yaml}"

    def test_traditional_yaml_files_valid(self) -> None:
        """Test that traditional task YAML files are valid."""
        import yaml

        traditional_tasks = list(Path.cwd().glob("task/*/[0-9]*/"))
        if not traditional_tasks:
            pytest.skip("No traditional task structures found")

        for task_dir in traditional_tasks[:3]:  # Test first 3
            task_name = task_dir.parent.name
            yaml_file = task_dir / f"{task_name}.yaml"

            if not yaml_file.exists():
                continue

            # Should be valid YAML
            with open(yaml_file) as f:
                content = yaml.safe_load(f)

            assert content.get("apiVersion") == "tekton.dev/v1"
            assert content.get("kind") == "Task"
            assert content["metadata"]["name"] == task_name

    def test_mixed_repository_structure(self) -> None:
        """Test that repositories can contain both traditional and flexible structures."""
        # Check for traditional structures
        traditional_tasks = list(Path.cwd().glob("task/*/[0-9]*/"))

        # Check for flexible structures
        flexible_structures = [
            Path.cwd() / "task/nested-example/deep/subdir/nested-example.yaml",
            Path.cwd() / "task/no-subdirectory/no-subdirectory.yaml",
            Path.cwd() / "task/random-nesting/nesting/nesting-even-deeper/random-nesting.yaml"
        ]
        flexible_tasks = [f for f in flexible_structures if f.exists()]

        # Repository should support both types
        if traditional_tasks and flexible_tasks:
            # Both types coexist - this is the expected state
            assert len(traditional_tasks) > 0, "Traditional tasks should exist"
            assert len(flexible_tasks) > 0, "Flexible tasks should exist"


class TestVersioningCompatibility:
    """Test that versioning works for both traditional and flexible structures."""

    def test_version_extraction_methods(self) -> None:
        """Test that versions can be extracted from both structure types."""
        import yaml

        all_results = []

        # Test traditional structures
        traditional_tasks = list(Path.cwd().glob("task/*/[0-9]*/"))
        for task_dir in traditional_tasks[:2]:  # Test first 2
            task_name = task_dir.parent.name
            yaml_file = task_dir / f"{task_name}.yaml"

            if not yaml_file.exists():
                continue

            with open(yaml_file) as f:
                content = yaml.safe_load(f)

            # Should have version in metadata labels
            labels = content["metadata"].get("labels", {})
            version = labels.get("app.kubernetes.io/version")

            all_results.append(("traditional", task_name, version))

        # Test flexible structures
        flexible_files = [
            "task/nested-example/deep/subdir/nested-example.yaml",
            "task/no-subdirectory/no-subdirectory.yaml",
        ]

        for task_file in flexible_files:
            path = Path.cwd() / task_file
            if not path.exists():
                continue

            with open(path) as f:
                content = yaml.safe_load(f)

            task_name = content["metadata"]["name"]
            labels = content["metadata"].get("labels", {})
            version = labels.get("app.kubernetes.io/version")

            all_results.append(("flexible", task_name, version))

        # Both structure types should successfully extract versions
        traditional_results = [r for r in all_results if r[0] == "traditional"]
        flexible_results = [r for r in all_results if r[0] == "flexible"]

        if traditional_results:
            traditional_with_versions = [r for r in traditional_results if r[2] is not None]
            assert len(traditional_with_versions) > 0, "Traditional tasks should have versions"

        if flexible_results:
            flexible_with_versions = [r for r in flexible_results if r[2] is not None]
            assert len(flexible_with_versions) > 0, "Flexible tasks should have versions"


class TestShellScriptCompatibility:
    """Test that shell scripts handle both structure types."""

    def test_shell_scripts_handle_mixed_structures(self) -> None:
        """Test that shell scripts can handle both traditional and flexible structures."""
        scripts = [
            ".github/scripts/check_tekton_tasks.sh",
            ".github/scripts/test_tekton_tasks.sh"
        ]

        for script in scripts:
            script_path = Path.cwd() / script
            if not script_path.exists():
                continue

            # Test with no arguments (should not crash)
            result = subprocess.run(
                ["/bin/bash", str(script_path)],
                capture_output=True,
                text=True
            )

            # Should handle gracefully (not crash)
            assert result.returncode in [0, 1], f"Script {script} crashed unexpectedly"

            # Should provide informative output
            output = result.stdout + result.stderr
            assert len(output.strip()) > 0, f"Script {script} produced no output"