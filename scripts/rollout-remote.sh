#!/usr/bin/env bash
# The rollout's hands on a machine the controller reaches over SSH (ADR 0081).
# The controller on the compute machine runs this on the droplet; it decides
# nothing itself.
#
#   rollout-remote.sh version            the release this machine runs, or none
#   rollout-remote.sh receive <name>     stdin into .rollout/<name>
#   rollout-remote.sh start <job> <cmd>  run <cmd> as job <job>, detached
#   rollout-remote.sh status <job>       running | ok | failed <code> | none
#   rollout-remote.sh log <job>          the end of the job's output
#   rollout-remote.sh dirty              local changes to tracked files, if any
#
# A job runs in its own session, detached from the SSH connection, so a
# connection the Mac drops by sleeping does not cut a migration off halfway;
# the controller asks for its status until it ends. Starting a job that already
# succeeded or still runs does nothing; one that failed runs again.
#
# The body is one function, read whole before it runs, because a job may
# check out another release and rewrite this file.
set -euo pipefail

remote() {
  cd "$(dirname "$0")/.."
  local jobs=.rollout/jobs
  mkdir -p "$jobs"

  case "${1:-}" in
    version)
      cat .rollout/deployed 2>/dev/null || echo none ;;
    receive)
      local name="${2:-}"
      [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "ERROR: bad file name '${name}'"; return 1; }
      cat > ".rollout/${name}.tmp" && mv ".rollout/${name}.tmp" ".rollout/${name}" ;;
    start)
      local job="${2:-}" command="${3:-}"
      [[ "$job" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "ERROR: bad job name '${job}'"; return 1; }
      [ -n "$command" ] || { echo "ERROR: start ${job} with no command"; return 1; }
      local state
      state="$(get_status "$job")"
      case "$state" in
        ok|running) echo "$state"; return 0 ;;
      esac
      rm -f "$jobs/$job.exit" "$jobs/$job.pid"
      # The exit code is written last, through a rename, so `status` never
      # reads a half-written one.
      setsid nohup bash -c "$command"'
        code=$?
        echo "$code" > "$0.exit.tmp" && mv "$0.exit.tmp" "$0.exit"' "$(pwd)/$jobs/$job" \
        > "$jobs/$job.log" 2>&1 < /dev/null &
      echo $! > "$jobs/$job.pid"
      echo started ;;
    status)
      get_status "${2:?name the job}" ;;
    log)
      tail -n 40 "$jobs/${2:?name the job}.log" 2>/dev/null || true ;;
    dirty)
      git status --porcelain --untracked-files=no ;;
    *)
      echo "usage: rollout-remote.sh version | receive <name> | start <job> <command> | status <job> | log <job> | dirty"
      return 1 ;;
  esac
}

get_status() {
  local jobs=.rollout/jobs job="$1"
  if [ -f "$jobs/$job.exit" ]; then
    local code
    code="$(cat "$jobs/$job.exit")"
    if [ "$code" = 0 ]; then echo ok; else echo "failed $code"; fi
  elif [ -f "$jobs/$job.pid" ] && kill -0 "$(cat "$jobs/$job.pid")" 2>/dev/null; then
    echo running
  else
    echo none
  fi
}

remote "$@"
exit
