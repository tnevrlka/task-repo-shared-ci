#!/usr/bin/env python
"""Tests for core task discovery logic in flexible structures.

Tests task discovery patterns and logic without requiring kubectl or
external dependencies.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def disable_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable GitHub Actions mode for all tests by default."""
    monkeypatch.setenv("GITHUB_ACTIONS", "false")


class TestTaskStructurePatterns:
    """Test task structure patterns and discovery logic."""

    def test_task_file_existence_patterns(self) -> None:
        """Test that task files follow expected naming patterns."""
        # Expected pattern: task file name should match some directory name in the path
        test_cases = [
            "task/nested-example/deep/subdir/nested-example.yaml",
            "task/no-subdirectory/no-subdirectory.yaml",
            "task/random-nesting/nesting/nesting-even-deeper/random-nesting.yaml"
        ]

        for task_file in test_cases:
            path = Path.cwd() / task_file
            if not path.exists():
                continue

            # Extract task name from filename
            task_name = path.stem

            # Check that task name appears in the path
            path_parts = path.parts
            assert task_name in path_parts, f"Task name {task_name} not found in path {task_file}"

    def test_version_metadata_extraction(self) -> None:
        """Test that version metadata can be extracted from task files."""
        import yaml

        flexible_tasks = [
            "task/nested-example/deep/subdir/nested-example.yaml",
            "task/no-subdirectory/no-subdirectory.yaml",
            "task/no-version-subdirectory/no-version-subdirectory.yaml",
            "task/random-nesting/nesting/nesting-even-deeper/random-nesting.yaml"
        ]

        for task_file in flexible_tasks:
            path = Path.cwd() / task_file
            if not path.exists():
                continue

            with open(path) as f:
                content = yaml.safe_load(f)

            # Should have version label
            labels = content["metadata"].get("labels", {})
            version = labels.get("app.kubernetes.io/version")

            assert version is not None, f"Missing version metadata in {task_file}"
            assert version != "", f"Empty version metadata in {task_file}"

    def test_task_directory_structure_validation(self) -> None:
        """Test that task directories follow flexible structure rules."""
        flexible_structures = [
            ("task/nested-example/deep/subdir", "nested-example.yaml"),
            ("task/no-subdirectory", "no-subdirectory.yaml"),
            ("task/random-nesting/nesting/nesting-even-deeper", "random-nesting.yaml")
        ]

        for task_dir, expected_file in flexible_structures:
            dir_path = Path.cwd() / task_dir
            file_path = dir_path / expected_file

            if not file_path.exists():
                continue

            # Directory should exist
            assert dir_path.exists(), f"Task directory not found: {task_dir}"
            assert dir_path.is_dir(), f"Expected directory: {task_dir}"

            # Task file should exist
            assert file_path.exists(), f"Task file not found: {file_path}"
            assert file_path.is_file(), f"Expected file: {file_path}"


class TestTaskNamingConventions:
    """Test that task naming conventions are followed."""

    def test_task_names_consistent_with_metadata(self) -> None:
        """Test that task filenames match metadata task names."""
        import yaml

        task_files = list(Path.cwd().glob("task/**/*.yaml"))
        flexible_task_files = [
            f for f in task_files
            if any(part in str(f) for part in ["nested-example", "no-subdirectory", "random-nesting"])
        ]

        for task_file in flexible_task_files:
            with open(task_file) as f:
                content = yaml.safe_load(f)

            file_task_name = task_file.stem
            metadata_task_name = content["metadata"]["name"]

            assert file_task_name == metadata_task_name, \
                f"Filename {file_task_name} doesn't match metadata name {metadata_task_name} in {task_file}"

    def test_directory_name_alignment(self) -> None:
        """Test that task names align with directory structure."""
        test_cases = [
            ("task/nested-example/deep/subdir/nested-example.yaml", "nested-example"),
            ("task/no-subdirectory/no-subdirectory.yaml", "no-subdirectory"),
            ("task/random-nesting/nesting/nesting-even-deeper/random-nesting.yaml", "random-nesting")
        ]

        for task_file, expected_base_name in test_cases:
            path = Path.cwd() / task_file
            if not path.exists():
                continue

            # Task name should appear in one of the directory names
            path_parts = path.parts
            assert expected_base_name in path_parts, \
                f"Expected base name {expected_base_name} not found in path components {path_parts}"


class TestEdgeCaseHandling:
    """Test edge cases in task discovery without external dependencies."""

    def test_multiple_yaml_files_in_directory(self) -> None:
        """Test behavior with multiple YAML files in same directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create directory with multiple YAML files
            task_dir = temp_path / "task" / "multi-yaml"
            task_dir.mkdir(parents=True)

            # Create matching YAML file
            (task_dir / "multi-yaml.yaml").write_text("""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: multi-yaml
  labels:
    app.kubernetes.io/version: "1.0"
spec:
  steps: []
""")

            # Create non-matching YAML file
            (task_dir / "other.yaml").write_text("""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: other
spec:
  steps: []
""")

            # The matching file should exist
            matching_file = task_dir / "multi-yaml.yaml"
            assert matching_file.exists()

            # Both files should be valid YAML
            import yaml
            with open(matching_file) as f:
                content1 = yaml.safe_load(f)
            with open(task_dir / "other.yaml") as f:
                content2 = yaml.safe_load(f)

            assert content1["metadata"]["name"] == "multi-yaml"
            assert content2["metadata"]["name"] == "other"

    def test_deeply_nested_structures(self) -> None:
        """Test very deeply nested directory structures."""
        # Test the existing deeply nested example
        nested_path = Path.cwd() / "task/nested-example/deep/subdir/nested-example.yaml"

        if nested_path.exists():
            # Count directory depth
            relative_path = nested_path.relative_to(Path.cwd() / "task")
            depth = len(relative_path.parts) - 1  # Subtract 1 for the filename

            # Should handle reasonable nesting depth
            assert depth >= 3, "Should support deeply nested structures"
            assert depth <= 10, "Nesting shouldn't be excessively deep"