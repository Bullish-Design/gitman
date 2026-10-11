#!/usr/bin/env bash
set -u

report_dir=/home/andrew/Documents/Projects/gitman/.scratch/projects/69-gitman-skill-investigation/reports/wave2
scenario=$1
shift
path_file="$report_dir/old-C-$scenario.path"
log_file="$report_dir/old-C-$scenario.log"

if [[ ${1:-} == --init ]]; then
  sandbox=$(mktemp -d "/tmp/gitman-old-C-$scenario.XXXXXX")
  mkdir "$sandbox/repo"
  printf '%s\n' "$sandbox" > "$path_file"
  cat > "$sandbox/jjconfig.toml" <<'EOF'
user.name = "Scenario User"
user.email = "scenario@example.invalid"
EOF
  printf '$ mktemp -d /tmp/gitman-old-C-%s.XXXXXX\n%s\n[exit 0]\n' "$scenario" "$sandbox" >> "$log_file"
  printf '$ mkdir repo; create isolated jjconfig.toml and export JJ_CONFIG, GIT_CONFIG_GLOBAL, GITMAN_WORKSPACE_ROOT\n[exit 0]\n' >> "$log_file"
  printf '%s\n' "$sandbox"
  exit 0
fi

sandbox=$(cat "$path_file")
export JJ_CONFIG="$sandbox/jjconfig.toml"
export GIT_CONFIG_GLOBAL=/dev/null
export GITMAN_WORKSPACE_ROOT="$sandbox/workspaces"
cd "$sandbox/repo" || exit 99
command_text=$1
printf '\n$ %s\n' "$command_text" >> "$log_file"
output_file=$(mktemp "$sandbox/output.XXXXXX")
bash -lc "$command_text" > "$output_file" 2>&1
code=$?
cat "$output_file" | tee -a "$log_file"
printf '[exit %d]\n' "$code" | tee -a "$log_file"
rm "$output_file"
exit "$code"
