# Bridge maintenance tools

Small helpers for editing the `ndi_matlab_python_bridge.yaml` files, written
during the NDI-python#211 drift burn-down and kept because the same edits come
up whenever a bridge entry is examined against NDI-matlab.

They are deliberately **textual**. The bridge YAMLs are hand-maintained: they
carry section comments, blank-line grouping and a deliberate key order, all of
which a `yaml.safe_load` / `yaml.dump` round trip destroys.

## The rule these exist to serve

`tests/test_matlab_bridge_hashes.py` gates two things: no entry may drift from
NDI-matlab, and every entry naming a `matlab_path` must carry a
`matlab_last_sync_hash`.

Recording or moving a hash **asserts that someone read that MATLAB file against
its Python counterpart**. When the port needed no change, that reading is the
only evidence there is — so `TestAHashChangeIsJustified` requires that a hash
change touching none of the entry's `python_path` files also change that
entry's `decision_log`, and that the log name the commit:

```yaml
decision_log: >
  ... NDI-matlab abc1234 renamed a local variable; no behavioural change,
  nothing to port.
```

This is not bureaucracy. It comes from VH-Lab/NDR-python#23, where one commit
added `matlab_last_sync_hash` to 20 bridge files at once, touching no Python —
asserting that 1148 MATLAB commits had been reviewed. They had not been, and a
missing Intan multi-file feature stayed hidden behind those claims.

## Tools

| tool | what it does |
|---|---|
| `addhash.py` | Insert `matlab_last_sync_hash` into an entry, defaulting to the commit that last touched that MATLAB file. |
| `decision_log.py` | Append a paragraph to an entry's `decision_log`, creating the field if the entry has none. |
| `pr_ci_status.sh` | Compact CI status for a list of PRs. Needs `$GH_TOKEN`; takes the repo from `origin`. |

Both Python tools identify an entry by **name and `matlab_path` together**.
Neither alone is unique: a method called `read` exists on many classes, and
several entries legitimately share one MATLAB path.

## Usage

```bash
export NDI_MATLAB_PATH=/path/to/NDI-matlab

python tools/bridge/addhash.py \
    src/ndi/fun/ndi_matlab_python_bridge.yaml "diff (session)" "+ndi/+fun/+session/diff.m"

python tools/bridge/decision_log.py \
    src/ndi/fun/ndi_matlab_python_bridge.yaml "diff (session)" "+ndi/+fun/+session/diff.m" \
    "NDI-matlab abc1234 reworded a comment; nothing to port."

tools/bridge/pr_ci_status.sh 251 252
```

Pass an explicit hash as `addhash.py`'s fourth argument to record a **later**
commit that did not touch the file — section 7 of the bridge spec allows either
form.

## The workflow they fit into

1. Read what MATLAB actually changed:
   ```bash
   git -C $NDI_MATLAB_PATH log  <hash>..HEAD -- src/ndi/<matlab_path>
   git -C $NDI_MATLAB_PATH diff <hash>..HEAD -- src/ndi/<matlab_path>
   ```
2. Port the behavioural change, or decide there is nothing to port.
3. `addhash.py` (or edit the existing hash).
4. `decision_log.py`, naming the commit and saying what you compared.
5. Verify:
   ```bash
   NDI_MATLAB_PATH=... NDI_BRIDGE_CHECK_STRICT=1 pytest tests/test_matlab_bridge_*.py
   ```
6. Prove the gate still bites, by setting the hash to `<commit>^` and watching
   the drift check name your entry. A gate you have not seen fail is a gate you
   have not tested.

## What is deliberately not here

The burn-down also used throwaway scripts for editing
`tests/bridge_drift_allowlist.yaml` — delisting rows, resolving the merge
conflicts that arise when several PRs delete different rows, recomputing the
header count. That allowlist is now **empty in both sections** and the gate
forbids adding to it, so those scripts have no remaining use and are not kept.

`TestAHashChangeIsJustified` also had a local stand-in while it was still in
review. It is on `main` now, so run the real test instead.
