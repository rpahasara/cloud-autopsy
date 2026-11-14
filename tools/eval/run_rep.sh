#!/usr/bin/env bash
# CA-P2-007a: one repetition of one frozen scenario on its own fresh disposable kind cluster.
#   tools/eval/run_rep.sh SCENARIO_ID REPETITION RECORDS_DIR
# Every step's status is recorded; a failure is recorded and the repetition still ends with a record. Nothing is
# retried. The collector token lives in a 0700 temp directory and is deleted with the cluster.
set -u
SC="$1"; REP="$2"; RECORDS="$3"
WORK="$(mktemp -d "${RUNNER_TEMP:-/tmp}/ca-eval.XXXXXX")"
OUT="$WORK/out"
CLUSTER="ca-eval-$(echo "$SC" | tr 'A-Z' 'a-z')-$REP-${GITHUB_RUN_ID:-local}"
STEPS="$WORK/steps.txt"
: > "$STEPS"
step() { echo "$1 $2" >> "$STEPS"; }

START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if ! python -I tools/eval/scenario.py render "$SC" "$WORK"; then
  step render failed
  python -I tools/eval/evaluate_run.py --scenario "$SC" --repetition "$REP" --out "$OUT" --steps "$STEPS"     --db-json "$WORK/db.json" --token-file "$WORK/none" --started "$START" --records "$RECORDS"
  rm -rf "$WORK"
  exit 0
fi
. "$WORK/params.env"

if "$KIND" create cluster --name "$CLUSTER" --config deploy/kind/cluster.yaml --wait 180s >/dev/null 2>&1; then
  step cluster ok
  export KUBECONFIG="$WORK/kubeconfig"
  "$KIND" get kubeconfig --name "$CLUSTER" > "$KUBECONFIG"
  prepare() {
    local ns
    for ns in ca-incident ${OTHER_NS}; do
      "$KUBECTL" create namespace "$ns" --dry-run=client -o yaml | "$KUBECTL" apply -f - >/dev/null || return 1
      "$KUBECTL" -n "$ns" create configmap ca-incident-workload --from-file=deploy/kind/incident_workload.py >/dev/null || return 1
    done
    "$KUBECTL" apply -f "$WORK/incident.yaml" >/dev/null || return 1
    if [ -n "$OTHER_NS" ]; then "$KUBECTL" apply -f "$WORK/other.yaml" >/dev/null || return 1; fi
    "$KUBECTL" -n ca-incident rollout status deployment/checkout-api --timeout=240s >/dev/null || return 1
    if [ -n "$OTHER_NS" ]; then "$KUBECTL" -n ca-other rollout status deployment/checkout-api --timeout=240s >/dev/null || return 1; fi
  }
  if prepare; then step workload ok; else step workload failed; fi

  umask 077
  CRED="$WORK/cred"; mkdir -p "$CRED"
  if [ "$RBAC" = "incident-nolog" ]; then RBAC_FILE=deploy/kind/rbac-incident-nolog.yaml; else RBAC_FILE=deploy/kind/rbac-incident.yaml; fi
  if "$KUBECTL" apply -f "$RBAC_FILE" >/dev/null && "$KUBECTL" create token ca-collector -n ca-collector --duration=30m > "$CRED/token"; then
    echo "::add-mask::$(cat "$CRED/token")"
    "$KUBECTL" config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > "$CRED/ca.crt"
    SERVER="$("$KUBECTL" config view -o jsonpath='{.clusters[0].cluster.server}')"
    step identity ok
    EXTRA=()
    [ -z "$LOG_MAX_BYTES" ] || EXTRA=(--log-max-bytes "$LOG_MAX_BYTES")
    timeout 420 python -I tools/collect_k8s.py --server "$SERVER" --ca-file "$CRED/ca.crt" --token-file "$CRED/token" \
      --namespace ca-incident --cluster-id ca-kind-synthetic --recording-id "ca-eval-$(echo "$SC" | tr 'A-Z' 'a-z')-$REP" \
      --out "$OUT" --watch-seconds 150 --probe-interval 5 --final-wait 60 --ordering-rules 0.3 \
      --pod-logs --declare-limit checkout-api:DB_POOL_MAX:pool.maxConnections --incident-window 20:140 --no-events \
      "${EXTRA[@]}" > "$WORK/collector.txt" 2>&1 &
    pid=$!
    sleep 25
    case "$ACTION_TYPE" in
      set_env) "$KUBECTL" -n "$ACTION_NS" set env deployment/checkout-api $ACTION_ENV >/dev/null && step action ok || step action failed ;;
      rollout_restart) "$KUBECTL" -n "$ACTION_NS" rollout restart deployment/checkout-api >/dev/null && step action ok || step action failed ;;
      *) step action failed ;;
    esac
    "$KUBECTL" -n "$ACTION_NS" rollout status deployment/checkout-api --timeout=180s >/dev/null && step rollout ok || step rollout failed
    wait "$pid"; code=$?
    step collector "$([ "$code" = 0 ] && echo ok || echo "exit_$code")"
    if [ -d "$OUT/bundle" ]; then
      .venv-db/bin/python -I tools/create_investigation.py "$OUT/bundle" --json > "$WORK/db.json" 2> "$WORK/db.err" \
        && step database ok || step database failed
    fi
  else
    step identity failed
  fi
else
  step cluster failed
fi

python -I tools/eval/evaluate_run.py --scenario "$SC" --repetition "$REP" --out "$OUT" --steps "$STEPS" \
  --db-json "$WORK/db.json" --token-file "$WORK/cred/token" --started "$START" --records "$RECORDS" \
  || echo "evaluate_run failed for $SC $REP"
"$KIND" delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
rm -rf "$WORK"
