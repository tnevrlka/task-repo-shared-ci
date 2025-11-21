#!/bin/bash
shopt -s nullglob
set -euo pipefail

# <TEMPLATED FILE!>
# This file comes from the templates at https://github.com/konflux-ci/task-repo-shared-ci.
# Please consider sending a PR upstream instead of editing the file directly.
# See the SHARED-CI.md document in this repo for more details.

if [ "$#" -eq 0 ]; then
    echo "No changed task directories provided, nothing to validate"
    exit 0
fi

find_task_yaml() {
    local task_dir="$1"

    # Try to find task YAML file by searching up the directory tree
    local search_dir="$task_dir"
    while [[ "$search_dir" != "." && "$search_dir" != "/" && "$search_dir" != "task" ]]; do
        # First try: look for YAML files where filename matches current directory name
        local dir_name="$(basename "$search_dir")"
        local candidate="$search_dir/$dir_name.yaml"
        if [[ -f "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi

        # Second try: look for any YAML file where filename matches a parent directory name
        local task_yaml=""
        while IFS= read -r -d '' yaml_file; do
            local file_name="$(basename "$yaml_file" .yaml)"
            local check_dir="$search_dir"
            while [[ "$check_dir" != "task" && "$check_dir" != "." ]]; do
                local check_name="$(basename "$check_dir")"
                if [[ "$check_name" == "$file_name" ]]; then
                    task_yaml="$yaml_file"
                    break 2
                fi
                check_dir="$(dirname "$check_dir")"
            done
        done < <(find "$search_dir" -maxdepth 1 -name "*.yaml" -type f -print0)

        if [[ -n "$task_yaml" ]]; then
            echo "$task_yaml"
            return 0
        fi

        search_dir="$(dirname "$search_dir")"
    done

    return 1
}

echo ">>> Applying and validating Tekton Tasks"

for TASK_DIR in "$@"; do
    TASK_YAML_PATH=$(find_task_yaml "$TASK_DIR")

    if [[ $? -eq 0 && -f "$TASK_YAML_PATH" ]]; then
        echo ">>> Validating Task: $TASK_YAML_PATH"
        kubectl apply -f "$TASK_YAML_PATH" --dry-run=server
    else
        echo "INFO: Task YAML not found in directory '$TASK_DIR'. A non-YAML file was changed, skipping..."
    fi
done

echo ">>> All changed tasks validated successfully."
