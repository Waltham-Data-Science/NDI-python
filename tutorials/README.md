# NDI-python Tutorials

## Prerequisites

- Python 3.10 or later
- Git
- NDI Cloud account (free at <https://www.ndi-cloud.com>)

## Installation

From the NDI-python repository root:

```bash
python -m venv venv
source venv/bin/activate   # Linux/macOS
# venv\Scripts\activate    # Windows

python ndi_install.py
```

This single command clones all dependencies, installs packages, and validates your setup. Run `python -m ndi check` at any time to re-verify.

## Cloud Credentials

Tutorials download datasets from NDI Cloud on first run. Set your credentials via environment variables:

```bash
export NDI_CLOUD_USERNAME="your-email@example.com"
export NDI_CLOUD_PASSWORD="your-password"
```

Or edit the `NDI_CLOUD_USERNAME` / `NDI_CLOUD_PASSWORD` variables at the top of each tutorial script.

## Available Tutorials

### Dabrowska — Rat Electrophysiology & Optogenetic Stimulation

- **Script:** `tutorial_67f723d574f5f79c6062389d.py`
- **Paper:** <https://doi.org/10.1016/j.celrep.2025.115768>
- **Dataset DOI:** <https://doi.org/10.63884/ndic.2025.jyxfer8m>
- **Size:** ~14,600 documents
- **First-run download:** ~4 minutes
- **Run:**
  ```bash
  python tutorials/tutorial_67f723d574f5f79c6062389d.py
  ```

### Jess Haley — C. elegans Behavior & E. coli Fluorescence

- **Script:** `tutorial_682e7772cdf3f24938176fac.py`
- **Paper:** <https://doi.org/10.7554/eLife.103191.3>
- **Dataset DOI:** <https://doi.org/10.63884/ndic.2025.pb77mj2s>
- **Size:** ~78,700 documents
- **First-run download:** ~60 minutes
- **Run:**
  ```bash
  python tutorials/tutorial_682e7772cdf3f24938176fac.py
  ```

Each tutorial generates an HTML file in the `tutorials/` directory with tables, plots, and analysis results.

**Tip:** Start with the Dabrowska tutorial first — it's faster and a good way to verify your setup before running the larger Jess Haley dataset.

## Notes

- **Virtual environment required.** The installer writes a `.pth` file into your venv's `site-packages`. Running without a venv may require elevated permissions and is not recommended.
- **Disk space.** The Jess Haley dataset is ~16 GB. Make sure you have enough free space under `~/Documents/MATLAB/Datasets/`.
- **Dataset storage location.** Downloaded datasets are saved to `~/Documents/MATLAB/Datasets/` (matching the MATLAB tutorial convention). This directory is created automatically on first download.
- **Tested on macOS.** Linux should work. Windows is untested — please report any issues.

## Troubleshooting

### ModuleNotFoundError: No module named 'vlt'

vhlab-toolbox-python is not on PyPI. Run `python ndi_install.py` or manually clone:

```bash
git clone https://github.com/VH-Lab/vhlab-toolbox-python.git ~/.ndi/tools/vhlab-toolbox-python
```

### Cannot find NDI root directory

Set the `NDI_ROOT` environment variable to your NDI-python repo directory, or run scripts from within the repo.

### Download takes a long time

The Jess Haley dataset has ~78,700 documents and takes about an hour on first download. Subsequent runs load from the local cache instantly.

### Cloud API timeout errors (HTTP 504)

Large dataset operations may hit the 30-second API timeout. The client retries automatically (2 retries with backoff). If errors persist, try again later.
