# NDI Symmetry Artifacts Instructions (Python — makeArtifacts)

This folder contains Python tests whose purpose is to generate standard NDI artifacts for symmetry testing with other NDI language ports (e.g., MATLAB).

## Rules for `make_artifacts` tests:

1. **Artifact Location**: Tests must store their generated artifacts in the system's temporary directory (`tempfile.gettempdir()`).
2. **Directory Structure**: Inside the temporary directory, artifacts must be placed in a specific nested folder structure:
   `NDI/symmetryTest/pythonArtifacts/<namespace>/<class_name>/<test_name>/`

   - `<namespace>`: The sub-package name under `make_artifacts`. For example, for a test located at `tests/symmetry/make_artifacts/session/`, the namespace is `session`.
   - `<class_name>`: The name of the test class (e.g., `buildSession`), written in camelCase to match MATLAB conventions.
   - `<test_name>`: The specific name of the test method being executed (e.g., `testBuildSessionArtifacts`), also in camelCase.

3. **Persistent Teardown**: The generated artifacts and the underlying NDI session database must persist in the temporary directory so that the MATLAB test suite can read them. Do **not** use `tmp_path` for the artifact output directory — only use it for the ephemeral session that is later *copied* to the artifact directory.

4. **Artifact Contents**: Every `makeArtifacts` test should produce at minimum:
   - A copy of the NDI session directory (including the `.ndi/` database folder).
   - A `jsonDocuments/` sub-directory containing one `<doc_id>.json` file per document in the session.
   - A `probes.json` file listing all probes as an array of `{"name", "reference", "type", "subject_id"}` objects.

5. **Imports**: Use the shared constant `PYTHON_ARTIFACTS` from `tests/symmetry/conftest.py` to build the artifact path.

## Example:

For a test class `TestBuildSession` in `tests/symmetry/make_artifacts/session/test_build_session.py` with a test method `test_build_session_artifacts`, the artifacts should be saved to:

```
<tempdir>/NDI/symmetryTest/pythonArtifacts/session/buildSession/testBuildSessionArtifacts/
```

## Computation-style artifacts (time / syncgraph)

Some subsystems are pure computations, not persisted document sets. For those the
artifact is a self-describing JSON of inputs + computed outputs rather than a
session-dir copy. See `time/test_time_convert.py`: it runs the shared
`tests/symmetry/_time_scenario` battery through the real
`ndi.time.syncgraph.time_convert` and writes `timeConvertCases.json` (the scenario
spec + each case's `out_time` / `out_epoch` / `msg`). The MATLAB side builds the
same `SCENARIO` referents, runs `CASES`, and writes a matching file;
`read_artifacts/time/` compares the two and skips until the MATLAB artifact exists
— full cross-language closure needs the MATLAB runtime.

The `fun/` namespace holds two more of these: `fun/test_path_safe_name.py`
(`pathSafeNameCases.json`) and `fun/test_what_varies.py`
(`whatVariesCases.json`), both built from the shared battery in
`tests/symmetry/_fun_cases.py`.

**Those two implement a written cross-language contract**, and it is not this
file: `tests/+ndi/+symmetry/FUN_CASES_SCHEMA.md` in NDI-matlab, whose MATLAB
counterpart is `tests/+ndi/+symmetry/+fun/cases.m`. Read the schema before
changing either side — a change here that is not also a change there is how the
suite starts comparing two different things. Four conventions from it are worth
copying to the next computation-style pair:

* **Compare rendered strings, not values.** Every compared value goes through one
  small language-neutral grammar (`_fun_cases.render`) first: numbers `%.12g`,
  non-finite in MATLAB's spelling (`NaN`/`Inf`/`-Inf`), text single-quoted,
  *every* container `[a, b]`, mappings `{key: value}` with keys sorted. That is
  what stops the usual symmetry-test rot — MATLAB `double` vs Python `int`,
  MATLAB cell vs Python list, `jsondecode` collapsing a one-element array. A
  field that is semantically a list even when it holds one element goes through
  `render_sequence`, which always brackets (`[5]`, never `5`).
* **Write strict JSON.** `jsonencode(...,'ConvertInfAndNaN',true)` writes NaN as
  `null` and Python's `json.dumps(allow_nan=True)` writes the non-standard `NaN`
  token; neither survives the round trip. Under the grammar the problem
  disappears — a NaN is already the *string* `'NaN'` before encoding — so
  `allow_nan=False` stops being a precaution and becomes a proof that nothing
  bypassed the renderer. (The earlier `"__NaN__"` sentinel is gone; if you need
  a sentinel, the grammar is not being applied.)
* **Carry the input in a form the other language can rebuild exactly.**
  `pathSafeNameCases.json` specifies each input as Unicode scalar values, not as
  a source literal, so neither side has to trust a file encoding, and it records
  *both* length counts (UTF-16 code units and code points) so the read side can
  prove both languages ran the same input before comparing outputs. That matters
  wherever the two languages count characters differently. `whatVariesCases.json`
  does the same job with `inputRendered`, which is compared: without it the suite
  could go green while silently comparing two different inputs.
* **Every field is always present, and cases join by name.** A field that does
  not apply is `""`, `[]` or `false`, never absent — that keeps `jsondecode`
  returning a clean struct array. Order is irrelevant to the comparison.

Divergences between the two languages live in one allow-list
(`_fun_cases.known_divergences`), not in a per-case policy field, and the read
side audits it: see the read-side INSTRUCTIONS.

## Object-type marker (`.ndi/ndi_object_type.txt`)

Every make test whose artifact is a session or dataset directory ends with
`assert_object_type_marker(artifact_dir, "session" | "dataset")` from
`tests/symmetry/_object_type_marker`. The inventory of those directories lives
in the same module and the read side iterates it, so a new session/dataset
artifact must be added there too.

## Adding a new symmetry test:

1. Create a sub-package under `make_artifacts/` named after the NDI domain (e.g., `session/`, `document/`, `probe/`).
2. Add a `test_<name>.py` file with a test class that builds an NDI session, populates it, and exports artifacts to the path described above.
3. Mirror the directory naming in MATLAB: `tests/+ndi/+symmetry/+makeArtifacts/+<namespace>/<ClassName>.m`.
4. Add a corresponding `readArtifacts` test that can verify the generated artifacts (see `tests/symmetry/read_artifacts/INSTRUCTIONS.md`).
