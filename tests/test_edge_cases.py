#!/usr/bin/env python
"""Edge cases and error handling tests for flexible task structure support.

Tests edge cases, malformed structures, and error conditions that can be
validated without requiring kubectl or external dependencies.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def disable_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable GitHub Actions mode for all tests by default."""
    monkeypatch.setenv("GITHUB_ACTIONS", "false")


class TestMalformedTaskFiles:
    """Test handling of malformed or invalid task YAML files."""

    def test_missing_version_metadata(self) -> None:
        """Test task files missing app.kubernetes.io/version label."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            task_file = temp_path / "task" / "no-version" / "no-version.yaml"
            task_file.parent.mkdir(parents=True)

            task_file.write_text("""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: no-version
  labels:
    some.other.label: "value"
spec:
  steps: []
""")

            # Should be valid YAML but missing version
            import yaml
            with open(task_file) as f:
                content = yaml.safe_load(f)

            assert content["metadata"]["name"] == "no-version"
            labels = content["metadata"].get("labels", {})
            assert "app.kubernetes.io/version" not in labels

    def test_invalid_yaml_syntax(self) -> None:
        """Test files with invalid YAML syntax."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            task_file = temp_path / "invalid.yaml"

            # Create YAML with syntax errors
            task_file.write_text("""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: invalid
  invalid: yaml: syntax: here:
""")

            # Should raise YAML parsing error
            import yaml
            with pytest.raises(yaml.YAMLError):
                with open(task_file) as f:
                    yaml.safe_load(f)

    def test_non_tekton_yaml_file(self) -> None:
        """Test YAML files that aren't Tekton tasks."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            yaml_file = temp_path / "config.yaml"

            yaml_file.write_text("""
apiVersion: v1
kind: ConfigMap
metadata:
  name: not-a-task
data:
  config: "This is not a task"
""")

            # Should be valid YAML but not a Tekton task
            import yaml
            with open(yaml_file) as f:
                content = yaml.safe_load(f)

            assert content.get("kind") == "ConfigMap"
            assert content.get("kind") != "Task"


class TestComplexDirectoryStructures:
    """Test complex directory structures and edge cases."""

    def test_very_deep_nesting(self) -> None:
        """Test very deeply nested directory structures."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create deeply nested structure (10 levels)
            nested_path = temp_path / "task" / "deep"
            for i in range(10):
                nested_path = nested_path / f"level{i}"
            nested_path.mkdir(parents=True)

            # Create task at deepest level
            task_file = nested_path / "deep.yaml"
            task_file.write_text("""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: deep
  labels:
    app.kubernetes.io/version: "1.0"
spec:
  steps: []
""")

            # Should be accessible
            assert task_file.exists()
            assert task_file.is_file()

            # Count nesting depth
            relative_path = task_file.relative_to(temp_path / "task")
            depth = len(relative_path.parts) - 1  # Subtract 1 for filename
            assert depth == 11  # task/deep + 10 levels

    def test_special_characters_in_names(self) -> None:
        """Test task names with special characters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Test various special characters (safe for filesystem)
            test_names = [
                "task-with-hyphens",
                "task_with_underscores",
                "task.with.dots",
                "task123with456numbers"
            ]

            for task_name in test_names:
                task_dir = temp_path / "task" / task_name
                task_dir.mkdir(parents=True)

                task_file = task_dir / f"{task_name}.yaml"
                task_file.write_text(f"""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: {task_name}
  labels:
    app.kubernetes.io/version: "1.0"
spec:
  steps: []
""")

                # Should create successfully
                assert task_file.exists()

                # Should be valid YAML
                import yaml
                with open(task_file) as f:
                    content = yaml.safe_load(f)
                assert content["metadata"]["name"] == task_name

    def test_multiple_yaml_files_same_directory(self) -> None:
        """Test directories with multiple YAML files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            task_dir = temp_path / "task" / "multi-file"
            task_dir.mkdir(parents=True)

            # Create multiple YAML files
            (task_dir / "multi-file.yaml").write_text("""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: multi-file
  labels:
    app.kubernetes.io/version: "1.0"
spec:
  steps: []
""")

            (task_dir / "other.yaml").write_text("""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: other-task
spec:
  steps: []
""")

            (task_dir / "config.yaml").write_text("""
apiVersion: v1
kind: ConfigMap
metadata:
  name: config
data:
  value: "test"
""")

            # All files should exist
            assert (task_dir / "multi-file.yaml").exists()
            assert (task_dir / "other.yaml").exists()
            assert (task_dir / "config.yaml").exists()

            # Should be able to identify the matching task file
            matching_files = list(task_dir.glob("multi-file.yaml"))
            assert len(matching_files) == 1


class TestErrorConditions:
    """Test various error conditions and edge cases."""

    def test_empty_directories(self) -> None:
        """Test behavior with empty directories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            empty_dir = temp_path / "task" / "empty-task"
            empty_dir.mkdir(parents=True)

            # Directory exists but is empty
            assert empty_dir.exists()
            assert empty_dir.is_dir()
            assert len(list(empty_dir.iterdir())) == 0

    def test_directories_without_yaml_files(self) -> None:
        """Test directories with no YAML files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            task_dir = temp_path / "task" / "no-yaml"
            task_dir.mkdir(parents=True)

            # Create non-YAML files
            (task_dir / "README.md").write_text("# No YAML files here")
            (task_dir / "script.sh").write_text("#!/bin/bash\necho 'no yaml'")
            (task_dir / "data.txt").write_text("Just some text")

            # Directory has files but no YAML
            assert task_dir.exists()
            assert len(list(task_dir.iterdir())) == 3
            yaml_files = list(task_dir.glob("*.yaml"))
            assert len(yaml_files) == 0

    def test_task_name_directory_mismatch(self) -> None:
        """Test cases where task names don't match directory expectations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            task_dir = temp_path / "task" / "expected-name"
            task_dir.mkdir(parents=True)

            # Create task with different name than directory suggests
            wrong_name_file = task_dir / "different-name.yaml"
            wrong_name_file.write_text("""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: different-name
  labels:
    app.kubernetes.io/version: "1.0"
spec:
  steps: []
""")

            # File exists but name doesn't match directory
            assert wrong_name_file.exists()

            # Extract names for comparison
            directory_name = task_dir.name  # "expected-name"
            file_name = wrong_name_file.stem  # "different-name"

            import yaml
            with open(wrong_name_file) as f:
                content = yaml.safe_load(f)
            metadata_name = content["metadata"]["name"]  # "different-name"

            # Names don't align with directory
            assert directory_name != file_name
            assert directory_name != metadata_name
            assert file_name == metadata_name  # But file and metadata should match


class TestFileSystemEdgeCases:
    """Test filesystem-related edge cases."""

    def test_case_sensitivity(self) -> None:
        """Test case sensitivity in file and directory names."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create directories with different cases
            task_dir = temp_path / "task" / "CamelCase"
            task_dir.mkdir(parents=True)

            # Test different case combinations
            files_to_test = [
                "CamelCase.yaml",  # Exact match
                "camelcase.yaml",  # All lowercase
                "CAMELCASE.yaml",  # All uppercase
            ]

            for filename in files_to_test:
                file_path = task_dir / filename
                file_path.write_text(f"""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: {filename.replace('.yaml', '')}
  labels:
    app.kubernetes.io/version: "1.0"
spec:
  steps: []
""")

                assert file_path.exists(), f"File creation failed: {filename}"

    def test_unicode_characters(self) -> None:
        """Test handling of unicode characters in paths (where supported)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            try:
                # Test basic unicode support
                task_dir = temp_path / "task" / "test-unicode"
                task_dir.mkdir(parents=True)

                task_file = task_dir / "test-unicode.yaml"
                task_file.write_text("""
apiVersion: tekton.dev/v1
kind: Task
metadata:
  name: test-unicode
  labels:
    app.kubernetes.io/version: "1.0"
  annotations:
    description: "Test with unicode: éñ中文"
spec:
  steps: []
""")

                assert task_file.exists()

                # Should be able to read unicode content
                content = task_file.read_text()
                assert "éñ中文" in content

            except (OSError, UnicodeError):
                # Skip if filesystem doesn't support unicode
                pytest.skip("Filesystem doesn't support unicode characters")