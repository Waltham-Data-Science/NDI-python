#!/bin/bash
# Compact CI status for one or more pull requests.
#
#     tools/bridge/pr_ci_status.sh 251 252 253
#
# Prints, per PR: mergeable_state, how many checks have completed, and the
# names of any that did not succeed. Needs $GH_TOKEN. The repository is taken
# from the `origin` remote, so this works from any checkout.
#
# Why not `gh pr checks`: the gh CLI is not always present in the sandboxes
# this repository is developed in, and this needs only curl and python3.
set -u

REPO=$(git config --get remote.origin.url \
    | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')
if [ -z "${REPO:-}" ]; then
    echo "could not determine the GitHub repo from remote.origin.url" >&2
    exit 1
fi

for pr in "$@"; do
    detail=$(curl -sS -H "Authorization: Bearer $GH_TOKEN" \
        "https://api.github.com/repos/$REPO/pulls/$pr")
    read -r sha state <<<"$(printf '%s' "$detail" | python3 -c "
import json, sys
p = json.load(sys.stdin)
print(p['head']['sha'], p.get('mergeable_state', '?'))
")"
    runs=$(curl -sS -H "Authorization: Bearer $GH_TOKEN" \
        "https://api.github.com/repos/$REPO/commits/$sha/check-runs?per_page=100" \
        | python3 -c "
import json, sys
rs = json.load(sys.stdin).get('check_runs', [])
if not rs:
    print('no checks yet'); raise SystemExit
done = [r for r in rs if r['status'] == 'completed']
bad = [r['name'] for r in done if r['conclusion'] not in ('success', 'skipped', 'neutral')]
tail = f' FAILED {bad}' if bad else (' ALL GREEN' if len(done) == len(rs) else ' running')
print(f'{len(done)}/{len(rs)}{tail}')
")
    echo "#$pr [$state]: $runs"
done
