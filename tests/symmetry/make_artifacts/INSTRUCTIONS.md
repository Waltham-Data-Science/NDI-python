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

## Adding a new symmetry test:

1. Create a sub-package under `make_artifacts/` named after the NDI domain (e.g., `session/`, `document/`, `probe/`).
2. Add a `test_<name>.py` file with a test class that builds an NDI session, populates it, and exports artifacts to the path described above.
3. Mirror the directory naming in MATLAB: `tests/+ndi/+symmetry/+makeArtifacts/+<namespace>/<ClassName>.m`.
4. Add a corresponding `readArtifacts` test that can verify the generated artifacts (see `tests/symmetry/read_artifacts/INSTRUCTIONS.md`).
