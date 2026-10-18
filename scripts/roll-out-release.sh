#!/usr/bin/env bash
# The rollout controller (ADR 0081). Runs on the machine whose deploy/<machine>/
# holds a `rollout` file, the compute machine, and deploys the GitHub Release
# marked Latest to every machine that file lists, in an order that keeps any
# writer from running while the schema changes:
#
#   1. prepare every machine that runs another version, while all still run:
#      the tag checked out, the images pulled, settings and schema checked;
#   2. stop the writers (the compute machine's worker drains first);
#   3. on the machine that migrates: stop-app, start-app (which migrates, with
#      no writer left), check-app;
#   4. start the writers on the new release.
#
# A step that fails before (2) leaves everything running the old release. One
# that fails after it leaves the writers stopped: their old images could not
# run on the new schema anyway. Either way the pass records the failure, and a
# later pass, after ROLLOUT_RETRY_SECONDS, carries on from where it stopped.
#
#   roll-out-release.sh run      one pass (`make roll-out`; launchd's agent)
#   roll-out-release.sh status   the release, each machine's version, the last pass
#   roll-out-release.sh check    whether a pass could run, changing nothing
#   roll-out-release.sh pause | resume
#
# A host script, not a container: it stops and starts this machine's stack and
# checks out the code that defines it, so it must outlive both. It needs only
# git, curl, ssh, make and Docker, which the machine has. Written for macOS's
# /bin/bash 3.2. The body is one function, read whole before it runs, because
# step 1 checks out another release and rewrites this file.
set -euo pipefail

controller() {
  cd "$(dirname "$0")/.."
  MACHINE="$(cat .machine 2>/dev/null || true)"
  ROLLOUT_FILE="deploy/${MACHINE}/rollout"
  STATE=.rollout
  if [ -z "$MACHINE" ] || [ ! -f "$ROLLOUT_FILE" ]; then
    echo "ERROR: this machine (${MACHINE:-none}) runs no rollout; the controller's machine has deploy/<machine>/rollout."
    return 1
  fi
  mkdir -p "$STATE/releases"
  RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  set -a
  # shellcheck source=/dev/null
  . ./"${ENV_FILE:-.env}"
  set +a
  load_machines

  case "${1:-}" in
    run) run_pass ;;
    status) show_status ;;
    check) check_ready ;;
    pause) touch "$STATE/paused"; echo "rollout: paused; make roll-out-resume starts it again." ;;
    resume) rm -f "$STATE/paused"; echo "rollout: resumed." ;;
    *) echo "usage: roll-out-release.sh run | status | check | pause | resume"; return 1 ;;
  esac
}

# --- the machines --------------------------------------------------------------

# deploy/<machine>/rollout: "<machine> <local|ssh> <migrates|writer>" per line.
load_machines() {
  MACHINES=""; MIGRATOR=""; WRITERS=""
  local name reach role
  while read -r name reach role; do
    case "$name" in ''|\#*) continue ;; esac
    case "$reach" in
      local) [ "$name" = "$MACHINE" ] || fail_config "$name is reached locally, but this machine is $MACHINE" ;;
      ssh) ;;
      *) fail_config "$name: reach '$reach' is not local or ssh" ;;
    esac
    case "$role" in
      migrates) [ -z "$MIGRATOR" ] || fail_config "two machines migrate"; MIGRATOR="$name" ;;
      writer) WRITERS="$WRITERS $name" ;;
      *) fail_config "$name: role '$role' is not migrates or writer" ;;
    esac
    MACHINES="$MACHINES $name"
    eval "REACH_$(key "$name")=$reach"
  done < "$ROLLOUT_FILE"
  [ -n "$MIGRATOR" ] || fail_config "no machine migrates"
}

fail_config() { echo "ERROR: ${ROLLOUT_FILE}: $*"; exit 1; }
key() { echo "$1" | tr -c 'A-Za-z0-9\n' '_'; }
reach_of() { eval "echo \$REACH_$(key "$1")"; }

# Runs a rollout-remote.sh command on a machine reached over SSH.
ssh_remote() {
  : "${ROLLOUT_REMOTE_HOST:?ROLLOUT_REMOTE_HOST is required to reach a machine over SSH}"
  : "${ROLLOUT_REMOTE_USER:?}" "${ROLLOUT_REMOTE_DIR:?}" "${ROLLOUT_SSH_KEY:?}"
  ssh -i "$ROLLOUT_SSH_KEY" \
    -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 \
    -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$PWD/$STATE/known_hosts" \
    -o ProxyCommand="$PWD/scripts/rollout-ssh-proxy.sh %h %p" \
    "${ROLLOUT_REMOTE_USER}@${ROLLOUT_REMOTE_HOST}" \
    "cd '${ROLLOUT_REMOTE_DIR}' && scripts/rollout-remote.sh $*"
}

version_of() {
  if [ "$(reach_of "$1")" = local ]; then
    cat "$STATE/deployed" 2>/dev/null || echo none
  else
    ssh_remote version
  fi
}

# --- logging -------------------------------------------------------------------

# One JSON line per event on stdout, which launchd appends to .rollout/rollout.log.
log() {
  local level="$1" event="$2" line pair name value
  shift 2
  line="{\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"level\":\"${level}\",\"service\":\"rollout\",\"trace_id\":\"${RUN_ID}\",\"event\":\"${event}\""
  for pair in "$@"; do
    name="${pair%%=*}"; value="${pair#*=}"
    value="${value//\\/\\\\}"; value="${value//\"/\\\"}"
    line="${line},\"${name}\":\"${value}\""
  done
  echo "${line}}"
}

# --- one step ------------------------------------------------------------------

# step <machine> <name> <command>: runs <command> on <machine> and waits for it.
# Locally its output goes to .rollout/steps.log; over SSH it runs as a detached
# job named for the version and step, and a failure shows the job's output.
step() {
  local machine="$1" name="$2" command="$3" started outcome=ok
  started="$(date +%s)"
  report "$machine" "$name" in_progress
  if [ "$(reach_of "$machine")" = local ]; then
    { echo "### ${RUN_ID} ${machine} ${name}"; } >> "$STATE/steps.log"
    bash -c "$command" >> "$STATE/steps.log" 2>&1 || outcome=failed
  else
    run_remote_job "${VERSION}-${name}" "$command" || outcome=failed
  fi
  log "$( [ "$outcome" = ok ] && echo INFO || echo ERROR )" rollout.step \
    machine="$machine" version="$VERSION" step="$name" outcome="$outcome" \
    duration_ms="$(( ($(date +%s) - started) * 1000 ))"
  [ "$outcome" = ok ]
}

run_remote_job() {
  local job="$1" command="$2" state deadline
  deadline=$(( $(date +%s) + ${ROLLOUT_STEP_TIMEOUT_SECONDS:-3600} ))
  ssh_remote start "$job" "$(printf '%q' "$command")" >/dev/null
  while :; do
    # A status the connection lost is asked again: the job runs on regardless.
    state="$(ssh_remote status "$job" 2>/dev/null || echo unreachable)"
    case "$state" in
      ok) return 0 ;;
      failed*|none)
        ssh_remote log "$job" >> "$STATE/steps.log" 2>&1 || true
        return 1 ;;
    esac
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "### ${job} still ${state} after ${ROLLOUT_STEP_TIMEOUT_SECONDS:-3600}s" >> "$STATE/steps.log"
      return 1
    fi
    sleep "${ROLLOUT_POLL_SECONDS:-5}"
  done
}

# --- reporting -------------------------------------------------------------------

# GitHub Deployments, one per machine and version, in an environment named for
# the machine: the repository's Environments page then shows what each runs,
# and GitHub emails a failure. Off while ROLLOUT_GITHUB_TOKEN is blank. A
# report that fails is logged and never fails the rollout.
github() {
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer ${ROLLOUT_GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" "$@"
}

# The deployment for <machine> at this version, made the first time it is asked for.
deployment_id() {
  local machine="$1" file reply id
  file="$STATE/deployments/${VERSION}-$(key "$machine")"
  if [ -s "$file" ]; then
    cat "$file"
    return 0
  fi
  reply="$(github -X POST "https://api.github.com/repos/$(repository)/deployments" \
    -d "{\"ref\":\"${VERSION}\",\"environment\":\"${machine}\",\"auto_merge\":false,\"required_contexts\":[],\"production_environment\":true,\"description\":\"rollout ${RUN_ID}\"}")" \
    || return 1
  id="$(sed -n 's/^  "id": \([0-9][0-9]*\),$/\1/p' <<<"$reply" | head -n 1)"
  [ -n "$id" ] || return 1
  mkdir -p "$STATE/deployments"
  echo "$id" > "$file"
  echo "$id"
}

# report <machine> <step> <in_progress|success|failure>
report() {
  [ -n "${ROLLOUT_GITHUB_TOKEN:-}" ] || return 0
  local machine="$1" name="$2" state="$3" id
  if id="$(deployment_id "$machine" 2>/dev/null)" \
    && github -X POST "https://api.github.com/repos/$(repository)/deployments/${id}/statuses" \
      -d "{\"state\":\"${state}\",\"environment\":\"${machine}\",\"description\":\"${name}\"}" >/dev/null 2>&1; then
    return 0
  fi
  log WARN rollout.report_failed machine="$machine" version="$VERSION" step="$name" state="$state"
}

# record_failure <step> <machine> <what it leaves running>
record_failure() {
  echo "$VERSION $1-$2 $(date +%s)" > "$STATE/failed"
  log ERROR rollout.failed version="$VERSION" step="$1-$2" detail="$3"
  report "$2" "$1 failed: $3" failure
}

# --- a pass --------------------------------------------------------------------

take_lock() {
  if mkdir "$STATE/lock" 2>/dev/null; then
    echo $$ > "$STATE/lock/pid"
    trap 'rm -rf "$STATE/lock"' EXIT
    return 0
  fi
  local holder
  holder="$(cat "$STATE/lock/pid" 2>/dev/null || true)"
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
    return 1
  fi
  # A pass that died without letting go.
  rm -rf "$STATE/lock"
  take_lock
}

# owner/repo on GitHub: ROLLOUT_REPOSITORY, else origin's.
repository() {
  if [ -n "${ROLLOUT_REPOSITORY:-}" ]; then
    echo "$ROLLOUT_REPOSITORY"
  else
    git remote get-url origin | sed -E 's#^(https://github\.com/|git@github\.com:)##; s#\.git$##'
  fi
}

latest_url() { echo "https://github.com/$(repository)/releases/latest/download/release.env"; }

run_pass() {
  if [ -f "$STATE/paused" ]; then
    log INFO rollout.paused
    return 0
  fi
  if ! take_lock; then
    log INFO rollout.busy detail="another pass is running"
    return 0
  fi

  if ! curl -fsSL --retry 2 -o "$STATE/latest.env.tmp" "$(latest_url)"; then
    log WARN rollout.unreachable detail="could not download the latest release"
    return 1
  fi
  mv "$STATE/latest.env.tmp" "$STATE/latest.env"
  VERSION="$(sed -n 's/^RELEASE_VERSION=//p' "$STATE/latest.env")"
  if ! [[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    log ERROR rollout.bad_release detail="the latest release names no RELEASE_VERSION"
    return 1
  fi

  local machine behind="" migrator_behind=no current
  for machine in $MACHINES; do
    if ! current="$(version_of "$machine")"; then
      log WARN rollout.unreachable machine="$machine"
      return 1
    fi
    if [ "$current" != "$VERSION" ]; then
      behind="$behind $machine"
      [ "$machine" != "$MIGRATOR" ] || migrator_behind=yes
    fi
  done
  if [ -z "$behind" ]; then
    rm -f "$STATE/failed"
    return 0
  fi

  if [ -f "$STATE/failed" ]; then
    local failed_version failed_step failed_at
    read -r failed_version failed_step failed_at < "$STATE/failed"
    if [ "$failed_version" = "$VERSION" ] \
      && [ "$(date +%s)" -lt $(( failed_at + ${ROLLOUT_RETRY_SECONDS:-1800} )) ]; then
      log INFO rollout.waiting version="$VERSION" step="$failed_step" detail="retrying after ROLLOUT_RETRY_SECONDS"
      return 0
    fi
  fi

  log INFO rollout.started version="$VERSION" machines="${behind# }"
  cp "$STATE/latest.env" "$STATE/releases/${VERSION}.env"

  # 1. Prepare, the migrating machine first. Nothing has stopped yet.
  for machine in $MIGRATOR $WRITERS; do
    case " $behind " in *" $machine "*) ;; *) continue ;; esac
    if [ "$(reach_of "$machine")" = local ]; then
      step "$machine" prepare "make --no-print-directory prepare-release RELEASE=$STATE/releases/${VERSION}.env" \
        || { record_failure prepare "$machine" "nothing was stopped"; return 1; }
    else
      ssh_remote receive "release-${VERSION}.env" < "$STATE/releases/${VERSION}.env"
      step "$machine" prepare "make --no-print-directory prepare-release RELEASE=.rollout/release-${VERSION}.env" \
        || { record_failure prepare "$machine" "nothing was stopped"; return 1; }
    fi
  done

  if [ "$migrator_behind" = yes ]; then
    # 2. Stop every writer: none may write while the schema changes.
    for machine in $WRITERS; do
      step "$machine" stop "make --no-print-directory stop-app" \
        || { record_failure stop "$machine" "a writer may still run; the migrating machine was not touched"; return 1; }
    done

    # 3. Deploy the migrating machine, which migrates with no writer left.
    step "$MIGRATOR" deploy "make --no-print-directory stop-app && make --no-print-directory start-app && make --no-print-directory check-app && echo ${VERSION} > .rollout/deployed" \
      || { record_failure deploy "$MIGRATOR" "the writers stay stopped until it succeeds"; return 1; }
    report "$MIGRATOR" deployed success
  fi

  # 4. Start the writers on the new release.
  for machine in $WRITERS; do
    case " $behind " in *" $machine "*) ;; *) continue ;; esac
    step "$machine" start "make --no-print-directory start-app && make --no-print-directory check-app && echo ${VERSION} > .rollout/deployed" \
      || { record_failure start "$machine" "the migrating machine runs ${VERSION}"; return 1; }
    report "$machine" deployed success
  done

  rm -f "$STATE/failed"
  log INFO rollout.finished version="$VERSION"
}

# --- status and check ------------------------------------------------------------

show_status() {
  local machine
  echo "Latest release: $(sed -n 's/^RELEASE_VERSION=//p' "$STATE/latest.env" 2>/dev/null || true)"
  for machine in $MACHINES; do
    echo "  ${machine}: $(version_of "$machine" 2>/dev/null || echo unreachable)"
  done
  if [ -f "$STATE/paused" ]; then echo "Paused: make roll-out-resume starts it again."; fi
  if [ -f "$STATE/failed" ]; then
    local version failed_step at
    read -r version failed_step at < "$STATE/failed"
    echo "Last failure: ${version} at ${failed_step}; the end of .rollout/steps.log says why."
  fi
  echo "Last events:"
  tail -n 5 "$STATE/rollout.log" 2>/dev/null | sed 's/^/  /' || true
}

check_ready() {
  local problems=0 machine
  if curl -fsSL -o /dev/null "$(latest_url)"; then
    echo "ok   the latest release downloads"
  else
    echo "FAIL the latest release does not download from $(latest_url)"; problems=1
  fi
  for machine in $MACHINES; do
    if [ "$(reach_of "$machine")" = local ]; then
      if [ -z "$(git status --porcelain --untracked-files=no)" ]; then
        echo "ok   ${machine}: checkout clean"
      else
        echo "FAIL ${machine}: checkout has local changes"; problems=1
      fi
    elif dirty="$(ssh_remote dirty 2>&1)"; then
      if [ -z "$dirty" ]; then
        echo "ok   ${machine}: answers over SSH, checkout clean"
      else
        echo "FAIL ${machine}: checkout has local changes"; problems=1
      fi
    else
      echo "FAIL ${machine}: does not answer over SSH: ${dirty}"; problems=1
    fi
  done
  return "$problems"
}

controller "$@"
exit
