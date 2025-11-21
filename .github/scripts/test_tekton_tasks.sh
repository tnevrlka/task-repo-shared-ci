#!/bin/bash

# <TEMPLATED FILE!>
# This file comes from the templates at https://github.com/konflux-ci/task-repo-shared-ci.
# Please consider sending a PR upstream instead of editing the file directly.
# See the SHARED-CI.md document in this repo for more details.

set -e
# This script will run task tests for all task directories
# provided either via TEST_ITEMS env var, or as arguments
# when running the script.
#
# Requirements:
# - Connection to a running k8s cluster (e.g. kind)
# - upstream konflux-ci installed on the cluster ( Follow steps from: https://github.com/konflux-ci/konflux-ci?tab=readme-ov-file#bootstrapping-the-cluster)
# - tkn installed
#
# Examples of usage:
# export TEST_ITEMS="task/git-clone/0.1 some/other/dir"
# ./test_tekton_tasks.sh
#
# or
#
# ./test_tekton_tasks.sh task/git-clone/0.1 some/other/dir

# Define a custom kubectl path if you like
KUBECTL_CMD=${KUBECTL_CMD:-kubectl}

# yield empty strings for unmatched patterns
shopt -s nullglob

WORKSPACE_TEMPLATE=${BASH_SOURCE%/*/*}/resources/workspace-template.yaml

if [[ -z $@ || ${1} == "-h" ]]; then
    cat <<EOF
Error: No task directories.

Usage:

$0 [item1] [item2] [...]

Example: ./.github/scripts/test_tekton_tasks.sh task/git-clone/0.1

or

export TEST_ITEMS="item1 item2 ..."

$0

Items can be task directories including version or paths to task test yaml files (useful when working on a single test)
EOF
  exit 1
fi

if [ $# -gt 0 ]; then
  TEST_ITEMS=$@
fi

# Check that all directories or test yamls exist. If not, fail
for ITEM in $TEST_ITEMS; do
  if [[ "$ITEM" == *tests/test-*.yaml && -f "$ITEM" ]]; then
    true
  elif [[ -d "$ITEM" ]]; then
    true
  else
    echo "Error: Invalid test yaml file or task directory: $ITEM"
    exit 1
  fi
done

find_task_info() {
  local item="$1"
  local task_dir=""
  local task_yaml=""

  if [[ "$item" == *tests/test-*.yaml ]]; then
    # It's a test file, find the task directory by going up directories
    task_dir="$(dirname "$(dirname "$item")")"
  else
    # It's a task directory
    task_dir="$item"
  fi

  # Try to find task YAML file by searching up the directory tree
  local search_dir="$task_dir"
  while [[ "$search_dir" != "." && "$search_dir" != "/" && "$search_dir" != "task" ]]; do
    # First try: look for YAML files where filename matches current directory name
    local dir_name="$(basename "$search_dir")"
    local candidate="$search_dir/$dir_name.yaml"
    if [[ -f "$candidate" ]]; then
      task_yaml="$candidate"
      task_dir="$search_dir"
      break
    fi

    # Second try: look for any YAML file where filename matches a parent directory name
    while IFS= read -r -d '' yaml_file; do
      local file_name="$(basename "$yaml_file" .yaml)"
      local check_dir="$search_dir"
      while [[ "$check_dir" != "task" && "$check_dir" != "." ]]; do
        local check_name="$(basename "$check_dir")"
        if [[ "$check_name" == "$file_name" ]]; then
          task_yaml="$yaml_file"
          task_dir="$(dirname "$yaml_file")"
          break 2
        fi
        check_dir="$(dirname "$check_dir")"
      done
    done < <(find "$search_dir" -maxdepth 1 -name "*.yaml" -type f -print0)

    [[ -n "$task_yaml" ]] && break
    search_dir="$(dirname "$search_dir")"
  done

  if [[ -z "$task_yaml" ]]; then
    echo "ERROR: Could not find task YAML file for item: $item" >&2
    return 1
  fi

  local task_name="$(basename "$task_yaml" .yaml)"
  local task_version="$(yq -r '.metadata.labels."app.kubernetes.io/version"' "$task_yaml" 2>/dev/null || echo "unknown")"

  echo "$task_dir $task_name $task_version $task_yaml"
}

for ITEM in $TEST_ITEMS; do
  echo "Test item: $ITEM"

  # Extract task information using flexible path detection
  TASK_INFO=($(find_task_info "$ITEM"))
  if [[ $? -ne 0 ]]; then
    exit 1
  fi

  TASK_DIR="${TASK_INFO[0]}"
  TASK_NAME="${TASK_INFO[1]}"
  TASK_VERSION="${TASK_INFO[2]}"
  TASK_PATH="${TASK_INFO[3]}"

  echo "DEBUG: Task name: $TASK_NAME"
  echo "DEBUG: Task version: $TASK_VERSION"
  echo "DEBUG: Task path: $TASK_PATH"

  TASK_VERSION_WITH_HYPHEN="$(echo $TASK_VERSION | tr '.' '-')"
  TEST_NS="${TASK_NAME}-${TASK_VERSION_WITH_HYPHEN}"
  # check if task file exists or not
  if [ ! -f $TASK_PATH ]; then
    echo "ERROR: Task file does not exist: $TASK_PATH"
    exit 1
  fi

  # Check if tests dir exists under task dir
  TESTS_DIR=${TASK_DIR}/tests
  if [ ! -d $TESTS_DIR ]; then
    echo "ERROR: tests dir does not exist: $TESTS_DIR"
    exit 1
  fi

  # check if tests yamls exists
  if [[ "$ITEM" == *tests/test-*.yaml ]]; then
    TEST_PATHS=($ITEM)
  else
    TEST_PATHS=($TESTS_DIR/test-*.yaml)
  fi
  if [ ${#TEST_PATHS[@]} -eq 0 ]; then
    echo "WARNING: No tests for test item $ITEM ... Skipping..."
    continue
  fi

  # Use a copy of the task file to prevent modifying the original task file
  TASK_COPY=$(mktemp /tmp/task.XXXXXX)
  clean() { rm -f ${TASK_COPY}; }
  trap clean EXIT

  cp "$TASK_PATH" "$TASK_COPY"

  # Create test namespace
  if ! ${KUBECTL_CMD} get namespace ${TEST_NS}; then
    ${KUBECTL_CMD} create namespace ${TEST_NS}
  fi

  # run the pre-apply-task-hook.sh if exists
  if [ -f ${TESTS_DIR}/pre-apply-task-hook.sh ]
  then
    echo "Found pre-apply-task-hook.sh file in dir: $TESTS_DIR. Executing..."
    ${TESTS_DIR}/pre-apply-task-hook.sh "$TASK_COPY" "$TEST_NS"
  fi

  # Create the service account appstudio-pipeline (konflux specific requirement)
  if ! ${KUBECTL_CMD} get sa appstudio-pipeline -n ${TEST_NS}; then
    ${KUBECTL_CMD} create sa appstudio-pipeline -n ${TEST_NS}
  fi

  # dry-run this YAML to validate and also get formatting side-effects.
  ${KUBECTL_CMD} -n ${TEST_NS} create -f ${TASK_COPY} --dry-run=client -o yaml

  echo "INFO: Installing task"
  ${KUBECTL_CMD} apply -f "$TASK_COPY" -n "$TEST_NS"

  for TEST_PATH in ${TEST_PATHS[@]}; do
    echo "========== Starting Test Pipeline: $TEST_PATH =========="
    echo "INFO: Installing test pipeline: $TEST_PATH"
    ${KUBECTL_CMD} -n ${TEST_NS} apply -f $TEST_PATH
    TEST_NAME=$(yq '.metadata.name' $TEST_PATH)

    # Sometimes the pipeline is not available immediately
    while ! ${KUBECTL_CMD} -n ${TEST_NS} get pipeline $TEST_NAME > /dev/null 2>&1; do
      echo "DEBUG: Pipeline $TEST_NAME not ready. Waiting 5s..."
      sleep 5
    done

    PIPELINERUN=$(tkn p start $TEST_NAME -n ${TEST_NS} -w name=tests-workspace,volumeClaimTemplateFile=$WORKSPACE_TEMPLATE  -o json | jq -r '.metadata.name')
    echo "INFO: Started pipelinerun: $PIPELINERUN"
    sleep 1  # allow a second for the prun object to appear (including a status condition)
    while [ "$(${KUBECTL_CMD} get pr $PIPELINERUN -n ${TEST_NS} -o=jsonpath='{.status.conditions[0].status}')" == "Unknown" ]; do
      echo "DEBUG: PipelineRun $PIPELINERUN is in progress (status Unknown). Waiting for update..."
      sleep 5
    done
    tkn pr logs $PIPELINERUN -n ${TEST_NS}

    PR_STATUS=$(${KUBECTL_CMD} get pr $PIPELINERUN -n ${TEST_NS} -o=jsonpath='{.status.conditions[0].status}')

    ASSERT_TASK_FAILURE=$(yq '.metadata.annotations.test/assert-task-failure' < $TEST_PATH)
    if [ "$ASSERT_TASK_FAILURE" != "null" ]; then
      if [ "$PR_STATUS" == "True" ]; then
        echo "INFO: Pipeline $TEST_NAME is succeeded but was expected to fail"
        exit 1
      else
        echo "DEBUG: Pipeline $TEST_NAME failed (expected). Checking that it failed in task ${ASSERT_TASK_FAILURE}..."

        # Check that the pipelinerun failed on the tested task and not somewhere else
        TASKRUN=$(${KUBECTL_CMD} get pr $PIPELINERUN -n ${TEST_NS} -o json|jq -r ".status.childReferences[] | select(.pipelineTaskName == \"${ASSERT_TASK_FAILURE}\") | .name")
        if [ -z "$TASKRUN" ]; then
          echo "ERROR: Unable to find task $ASSERT_TASK_FAILURE in childReferences of pipelinerun $PIPELINERUN. Pipelinerun failed earlier?"
          exit 1
        else
          echo "DEBUG: Found taskrun $TASKRUN"
        fi
        if [ $(${KUBECTL_CMD} get tr $TASKRUN -n ${TEST_NS} -o=jsonpath='{.status.conditions[0].status}') != "False" ]; then
          echo "ERROR: Taskrun did not fail - pipelinerun failed later on?"
          exit 1
        else
          echo "INFO: Taskrun failed as expected"
        fi

      fi
    else
      if [ "$PR_STATUS" == "True" ]; then
        echo "INFO: Pipelinerun $TEST_NAME succeeded"
      else
        echo "ERROR: Pipelinerun $TEST_NAME failed"
        exit 1
      fi
    fi

    echo "========== Completed: $TEST_PATH =========="
  done

done
