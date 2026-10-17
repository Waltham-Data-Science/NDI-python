<#
.SYNOPSIS
  Install NDI-python for end users on Windows.

.DESCRIPTION
  powershell -ExecutionPolicy Bypass -NoProfile -c "irm https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main/install/install-ndi.ps1 | iex"

  or double-click "Install NDI.cmd", or run this file. Run it again to update.
  Developers want `pip install -e .` instead; this is for people who just want
  the ndi, napariViewGEF and napariViewLightsheet commands.

  WHAT IT TOUCHES. Everything lives under %USERPROFILE%\.ndi, which NDI-matlab
  shares, and this script owns ONLY three folders there:
    .ndi\bin      uv itself, plus ndi.exe / napariViewGEF.exe / napariViewLightsheet.exe
    .ndi\python   the Python interpreter uv downloads (UV_PYTHON_INSTALL_DIR)
    .ndi\venvs    the environment NDI is installed into (UV_TOOL_DIR)
  Everything else in .ndi (NDI_Preferences.json, tools, caches, ...) is never
  touched, by install or by -Uninstall. Outside .ndi it changes only your
  user-level PATH (unless -NoPath); and uv keeps its download cache in its
  usual place (%LOCALAPPDATA%\uv\cache), shared with any other uv you use.
  No administrator rights, ever.

  FOR TESTING (CI uses these; end users never need them):
    NDI_INSTALL_SOURCE         what to install instead of the main branch:
                               a local checkout directory, or a URL
    NDI_PYRAVIEW_FIND_LINKS    URL of the Pyraview wheel index (install/pyraview-wheels.html)
    NDI_PYRAVIEW_CONSTRAINTS   URL or path of install/pyraview-constraints.txt
    NDI_INSTALL_PYTHON         the uv Python request instead of 3.12

  This is the contract NDI-matlab codes against: the folders above, the
  switches, exit status 0 only when the post-install check passed, and, on
  success, a last line of output reading `NDI installed: <path of .ndi\bin>`.
  Keep install/install-ndi.sh in step with it.

.PARAMETER Yes
  Do not ask before installing (MATLAB always passes this).
.PARAMETER NoPath
  Do not add .ndi\bin to the user PATH.
.PARAMETER Uninstall
  Remove what this script installed, and nothing else.
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$NoPath,
    [switch]$Uninstall
)

# Works in Windows PowerShell 5.1 and PowerShell 7: no ?? or ?: operators.
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest's bar is very slow on 5.1

# ---- pinned versions: the one place to change them ---------------------------
$UvVersion = '0.11.32'      # https://github.com/astral-sh/uv/releases
$PythonVersion = '3.12'
# ------------------------------------------------------------------------------

$RepoRaw = 'https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main'
$DefaultSource = 'https://github.com/Waltham-Data-Science/NDI-python/archive/refs/heads/main.zip'
# gui: the PySide6 apps; napari: the two viewers; pyraview: signal pyramids.
$Extras = 'gui,napari,pyraview'

$NdiHome = Join-Path $env:USERPROFILE '.ndi'
$Bin = Join-Path $NdiHome 'bin'
$PyDir = Join-Path $NdiHome 'python'
$Venvs = Join-Path $NdiHome 'venvs'

function Fail([string]$Reason) {
    # One line saying why, and a nonzero exit. [Console]::Error so it is
    # plain text on 5.1 rather than a red ErrorRecord block.
    [Console]::Error.WriteLine("NDI install failed: $Reason")
    exit 1
}

# PowerShell 5.1 may not offer TLS 1.2 by default; GitHub and astral.sh need it.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# Started from MATLAB: nothing here needs Python's own variables, and they can
# point the Python that builds and checks NDI at the wrong library. (MATLAB's
# effect on Windows is unmeasured; see src/_ndi_launch.py.)
Remove-Item Env:PYTHONHOME, Env:PYTHONPATH -ErrorAction SilentlyContinue

# ---- the user PATH -----------------------------------------------------------
# Read and written as the raw registry value so %VARIABLES% in it stay
# unexpanded (REG_EXPAND_SZ): the stock entry %USERPROFILE%\AppData\Local\
# Microsoft\WindowsApps would otherwise be flattened. The same approach uv's
# own installer takes. A dummy SetEnvironmentVariable broadcasts the change so
# new windows see it.

$EnvKey = 'registry::HKEY_CURRENT_USER\Environment'

# Entries are kept exactly, empty ones included (a trailing ';' is common),
# so that adding and then removing ours gives back the identical string.
function Get-UserPathEntries {
    $raw = [string](Get-Item -LiteralPath $EnvKey).GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    return , @($raw -split ';')
}

function Test-IsNdiBin([string]$Entry) {
    return $Entry.TrimEnd('\') -ieq $Bin.TrimEnd('\')
}

function Set-UserPathEntries([string[]]$Entries) {
    Set-ItemProperty -Type ExpandString -LiteralPath $EnvKey -Name Path -Value ($Entries -join ';')
    $dummy = 'NDI-installer-' + [guid]::NewGuid().ToString()
    [Environment]::SetEnvironmentVariable($dummy, '1', 'User')
    [Environment]::SetEnvironmentVariable($dummy, [NullString]::Value, 'User')
}

function Add-NdiToPath {
    $entries = Get-UserPathEntries
    if (@($entries | Where-Object { Test-IsNdiBin $_ }).Count -gt 0) {
        Write-Host "  $Bin is already on your PATH"
        return
    }
    # Appended, not prepended, so the uv in .ndi\bin never shadows one of yours;
    # before a trailing empty entry, so "a;b;" becomes "a;b;<bin>;".
    $n = $entries.Count
    if ($entries[$n - 1] -eq '') {
        if ($n -gt 1) { $new = @($entries[0..($n - 2)]) + $Bin + '' } else { $new = @($Bin, '') }
    } else {
        $new = @($entries) + $Bin
    }
    Set-UserPathEntries $new
    Write-Host "  added $Bin to your PATH"
}

function Remove-NdiFromPath {
    $entries = Get-UserPathEntries
    $kept = @($entries | Where-Object { -not (Test-IsNdiBin $_) })
    if ($kept.Count -ne $entries.Count) {
        Set-UserPathEntries $kept
        Write-Host "  removed $Bin from your PATH"
    }
}

# ---- uninstall ---------------------------------------------------------------

if ($Uninstall) {
    Write-Host "Removing NDI from $NdiHome (bin, python, venvs) ..."
    foreach ($d in @($Bin, $PyDir, $Venvs)) {
        if (Test-Path -LiteralPath $d) {
            try { Remove-Item -LiteralPath $d -Recurse -Force }
            catch { Fail "could not remove $d (is an NDI program still running?)" }
        }
    }
    Remove-NdiFromPath
    Write-Host "Your NDI settings and anything else in $NdiHome were left in place."
    Write-Output "NDI uninstalled: $Bin"
    exit 0
}

# ---- install -----------------------------------------------------------------

Write-Host 'NDI installer'
Write-Host "  installs into: $NdiHome (bin, python, venvs)"
Write-Host '  needs about 3 GB of disk and a few minutes on a good connection'
if (-not $Yes -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    $answer = Read-Host 'Continue? [Y/n]'
    if ($answer -and $answer -notmatch '^(y|yes)$') { Fail 'cancelled' }
}

try { New-Item -ItemType Directory -Force -Path $Bin, $PyDir, $Venvs | Out-Null }
catch { Fail "could not create folders in $NdiHome" }

# 1. uv, pinned. Astral's versioned installer, told to put uv in .ndi\bin.
# UV_UNMANAGED_INSTALL also stops it writing an update receipt (which would
# redirect a `uv self update` of a uv you already have to this copy) and
# stops it editing your PATH itself. It runs in a child PowerShell so its
# variables and settings cannot leak into this script.
$Uv = Join-Path $Bin 'uv.exe'
function Get-UvVersion {
    if (-not (Test-Path -LiteralPath $Uv)) { return '' }
    try { return ((& $Uv --version) -split ' ')[1] } catch { return '' }
}
if ((Get-UvVersion) -eq $UvVersion) {
    Write-Host "uv $UvVersion is already in $Bin"
} else {
    Write-Host "Downloading uv $UvVersion ..."
    $env:UV_INSTALL_DIR = $Bin
    $env:UV_UNMANAGED_INSTALL = $Bin
    $env:UV_NO_MODIFY_PATH = '1'
    $shell = (Get-Process -Id $PID).Path
    $cmd = "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; " +
        "irm https://astral.sh/uv/$UvVersion/install.ps1 | iex"
    & $shell -NoProfile -ExecutionPolicy Bypass -Command $cmd
    $uvExit = $LASTEXITCODE
    Remove-Item Env:UV_INSTALL_DIR, Env:UV_UNMANAGED_INSTALL -ErrorAction SilentlyContinue
    if ($uvExit -ne 0) { Fail 'could not download or run the uv installer from astral.sh' }
    if ((Get-UvVersion) -ne $UvVersion) { Fail "uv $UvVersion did not end up in $Bin" }
}

# 2. NDI, as a uv "tool": its own environment, its own managed Python, and its
# commands placed in .ndi\bin. Each setting keeps uv inside the three folders
# above and away from anything else on this machine:
$env:UV_PYTHON_INSTALL_DIR = $PyDir        # the interpreter
$env:UV_TOOL_DIR = $Venvs                  # the environment
$env:UV_TOOL_BIN_DIR = $Bin                # the commands
$env:UV_PYTHON_PREFERENCE = 'only-managed' # never a system/Store/conda Python that may vanish
$env:UV_NO_CONFIG = '1'                    # ignore any uv.toml of yours
$env:UV_NO_MODIFY_PATH = '1'

$Source = [Environment]::GetEnvironmentVariable('NDI_INSTALL_SOURCE')
if (-not $Source) { $Source = $DefaultSource }
if (Test-Path -LiteralPath $Source) {
    # A local checkout (CI): a file:/// URL to its absolute path.
    $Source = ([System.Uri](Resolve-Path -LiteralPath $Source).ProviderPath).AbsoluteUri
}
$FindLinks = [Environment]::GetEnvironmentVariable('NDI_PYRAVIEW_FIND_LINKS')
if (-not $FindLinks) { $FindLinks = "$RepoRaw/install/pyraview-wheels.html" }
$Constraints = [Environment]::GetEnvironmentVariable('NDI_PYRAVIEW_CONSTRAINTS')
if (-not $Constraints) { $Constraints = "$RepoRaw/install/pyraview-constraints.txt" }
$PythonRequest = [Environment]::GetEnvironmentVariable('NDI_INSTALL_PYTHON')
if (-not $PythonRequest) { $PythonRequest = $PythonVersion }

Write-Host "Installing NDI from $Source ..."
# --reinstall (which implies --refresh) so that running this again really
#   updates: NDI and its GitHub-archive dependencies are re-fetched.
# Pyraview is not on PyPI: its release wheels are found through FindLinks,
#   Constraints pins the version, and --no-build-package makes a missing wheel
#   an error rather than a C++ compile. See pyproject.toml's pyraview extra.
# PATH includes .ndi\bin from here on (this process only), so uv does not warn that the
#   folder is not on the PATH; step 4 deals with that.
$env:PATH = "$Bin;$env:PATH"
& $Uv tool install `
    --python $PythonRequest `
    --reinstall `
    --find-links $FindLinks `
    --constraints $Constraints `
    --no-build-package pyraview `
    "ndi[$Extras] @ $Source"
if ($LASTEXITCODE -ne 0) { Fail 'uv could not install NDI (see the messages above)' }

# 3. Check the result: the commands MATLAB will call, and `ndi check`.
Write-Host 'Checking the installation ...'
foreach ($c in @('ndi', 'napariViewGEF', 'napariViewLightsheet')) {
    if (-not (Test-Path -LiteralPath (Join-Path $Bin "$c.exe"))) { Fail "$Bin\$c.exe is missing" }
}
foreach ($c in @('napariViewGEF', 'napariViewLightsheet')) {
    & (Join-Path $Bin "$c.exe") --help | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "$c --help did not run" }
}
# 'Continue' while capturing: under 'Stop', Windows PowerShell 5.1 turns any
# line the program writes to stderr into a terminating error.
$ErrorActionPreference = 'Continue'
$checkOutput = & (Join-Path $Bin 'ndi.exe') check 2>&1
$checkExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($checkExit -ne 0) {
    $checkOutput | ForEach-Object { Write-Host $_ }
    Fail 'ndi check reported problems (see above)'
}
Write-Host '  ndi check: all checks passed'

# 4. PATH.
if (-not $NoPath) {
    Add-NdiToPath
    Write-Host 'Open a new terminal window to use the ndi, napariViewGEF and napariViewLightsheet commands.'
} else {
    Write-Host "PATH left alone (-NoPath); the commands are in $Bin"
}

Write-Output "NDI installed: $Bin"
