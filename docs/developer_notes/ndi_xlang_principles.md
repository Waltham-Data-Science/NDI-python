# NDI Cross-Language (MATLAB/Python) Principles

- **Status:** Active
- **Scope:** Universal (Applies to all NDI implementations)
- **Goal:** Zero-friction cognitive switching for researchers.

## 1. Indexing & Counting (The Semantic Parity Rule)

We distinguish between **Computer Science Indexing**, **Scientific Counting**, and **Sample Indices** (which are neither).

- **Implementation (0-vs-1):**
  - Python implementations MUST use 0-indexing for internal data structures (lists, arrays, dataframes).
  - MATLAB implementations MUST use 1-indexing for internal structures.
- **User-Facing Concepts (Counting from 1):**
  - **The Rule:** Any NDI concept that is "counted" (Epochs, Channels, Trials, Probes) MUST use 1-based numbering in both languages.
  - **Reasoning:** If a scientist records "Channel 1," it must be called "Channel 1" in both MATLAB and Python. If Python used "Channel 0," it would create a dangerous "off-by-one" error when comparing results across platforms.
  - **Implementation:** Python code must accept `channel_number=1` from the user, but internally map it to `data[0]`.
- **Sample Indices (0 in Python, 1 in MATLAB):**
  - **The Rule:** Positions within an epoch's sample timeline — the `s0`/`s1` of `readchannels_epochsamples[_ingested]`, the return of `epochtimes2samples[_ingested]`, and the argument to `epochsamples2times[_ingested]` — are **0-based in Python and 1-based in MATLAB**. `t = t0` maps to sample `0` in Python and sample `1` in MATLAB; `-Inf` clamps to `0` (Python) vs `1` (MATLAB); `epochtimes2samples([t0, t1])` returns `[0, N-1]` (Python) vs `[1, N]` (MATLAB).
  - **Reasoning:** A sample index names a position in a NumPy array, not a scientific count. Requiring Python users to write `data[s-1]` after every `epochtimes2samples` call would fight NumPy in every downstream expression, so the port follows the CS-indexing rule rather than the Scientific-Counting rule here.
  - **The Trap:** This is the one place a caller migrating a script between languages MUST adjust literal sample numbers by 1. `readchannels_epochsamples_ingested(..., s0=1, s1=100, ...)` reads samples 1..100 in MATLAB and samples 1..100 in Python — but "sample 1" in Python is the *second* sample, so the two produce off-by-one results. A one-line comment naming this divergence sits on `epochtimes2samples[_ingested]` and `epochsamples2times[_ingested]` in `src/ndi/daq/ndi_matlab_python_bridge.yaml` (the mfdaq_reader entries and the daq/system entries) and on the same methods' docstrings in `src/ndi/daq/mfdaq.py`. Documented as a permanent divergence in NDI-python#313.

## 2. Data Containers

- **Decision:** Prefer NumPy over Lists.
- **Rule:** Any MATLAB `double` array or matrix should be represented as a `numpy.ndarray` in Python, not a native Python list.
- **Rationale:** Neuroscience data is high-dimensional. NumPy provides the performance and slicing capabilities that match MATLAB's matrix engine.

## 3. Multiple Returns (Outputs)

- **Decision:** Explicit Tuple Returns.
- **Rule:** Python functions must return multiple values as a tuple in the exact order specified in the MATLAB function signature.
- **Parity:** If MATLAB returns `[data, information]`, Python must return `(data, information)`.

## 4. Logical Values (Booleans)

- **Decision:** Strict Boolean Mirroring.
- **Rule:** MATLAB `1`/`0` (logical) must be Python `True`/`False`.
- **Pydantic Role:** Use Pydantic to allow the string `"true"` or `"false"` to be coerced into Python booleans for API robustness.

## 5. Character Arrays vs. Strings

- **Decision:** Universal String Handling.
- **Rule:** MATLAB `char` and `string` are both treated as Python `str`.
- **Handling Lists:** A MATLAB cell array of strings must be a Python `list[str]`.

## 6. Error Philosophy (Hard Fail)

- **Decision:** No Silent Failures.
- **Rule:** If MATLAB issues an `error`, Python MUST raise an exception (e.g., `ValueError`, `TypeError`).
- **Parity:** Ensure the exception is raised at the same logical checkpoint as the MATLAB error.

## Instructions for AI Agents

1. **Data Indexing:** Use 0-indexing for Python list/array access.
2. **Scientific Counting:** Maintain 1-based counting for Epochs, Channels, and Trials. If a user passes `epoch_id=1`, do not subtract 1 unless you are using it to index an internal array.
3. **Sample Indices:** The `s0`/`s1` of `readchannels_epochsamples[_ingested]` and the return of `epochtimes2samples[_ingested]` are 0-based in Python and 1-based in MATLAB. Do NOT rewrite either side to match the other; both are documented and load-bearing.
4. **NumPy:** Always prioritize `numpy.ndarray` for numerical data.
5. **Bridge File:** Consult the local `ndi_matlab_python_bridge.yaml` to see if specific counting overrides exist for a function.
