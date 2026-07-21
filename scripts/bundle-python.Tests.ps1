# Pester 5 unit tests for scripts/bundle-python.ps1
#
# These tests are static-analysis style — they parse the script with
# PowerShell's AST and assert the fail-fast error handling is in place.
# They do NOT execute the full bundle pipeline (which downloads ~20MB of
# Python embeddable, takes minutes, and depends on network access).
#
# Goal: catch regressions of the v0.4.0-lts+ "30s backend timeout" bug
# where pip failures were silently swallowed by the script.
#
# Run locally:
#   pwsh -Command "Install-Module Pester -Force -Scope CurrentUser; Invoke-Pester -Path scripts/bundle-python.Tests.ps1"
#
# Run in CI: see .github/workflows/ci.yml `bundle-script-test` job.

BeforeAll {
    $Script:ScriptPath = Join-Path $PSScriptRoot 'bundle-python.ps1'
    if (-not (Test-Path $Script:ScriptPath)) {
        throw "Cannot find bundle-python.ps1 at $Script:ScriptPath"
    }
    $Script:ScriptContent = Get-Content -Path $Script:ScriptPath -Raw
    $Script:Tokens = $null
    $Script:Errors = $null
    $Script:null = [System.Management.Automation.Language.Parser]::ParseInput(
        $Script:ScriptContent,
        [ref]$Script:Tokens,
        [ref]$Script:Errors
    )
}

Describe 'bundle-python.ps1: AST parse' {
    It 'has no PowerShell syntax errors' {
        $Script:Errors | Should -BeNullOrEmpty
    }
}

Describe 'bundle-python.ps1: fail-fast guards on external invocations' {

    It 'declares $ErrorActionPreference = "Stop" at the top' {
        $Script:ScriptContent | Should -Match '\$ErrorActionPreference\s*=\s*"Stop"'
    }

    It 'checks $LASTEXITCODE after the get-pip.py install' {
        # The `& $PythonExe $GetPipPath --no-warn-script-location` call must be
        # followed by an explicit $LASTEXITCODE throw before the next statement.
        $pattern = '(?s)& \$PythonExe \$GetPipPath.*?if \(\$LASTEXITCODE -ne 0\) \{ throw'
        $Script:ScriptContent | Should -Match $pattern
    }

    It 'checks $LASTEXITCODE after pip install -r requirements' {
        # The critical regression guard — this is what the v0.4.0-lts+ bug
        # lacked. Without this, pip install failures get silently swallowed.
        $pattern = '(?s)& \$PipExe install .*? -r \$RequirementsFile.*?if \(\$LASTEXITCODE -ne 0\) \{ throw'
        $Script:ScriptContent | Should -Match $pattern
    }

    It 'checks $LASTEXITCODE after pip install -e sage-core' {
        $pattern = '(?s)& \$PipExe install .*? -e \$SageCoreDest.*?if \(\$LASTEXITCODE -ne 0\) \{ throw'
        $Script:ScriptContent | Should -Match $pattern
    }

    It 'checks exit code in the post-install verify step' {
        # The `& $PythonExe -c "..."` verify step must capture and check
        # $LASTEXITCODE rather than relying on pipeline success.
        # Note: split into two assertions because the f-string
        # `print(f'Python {sys.version}')` in the verify command contains
        # curly braces that confuse the regex engine's quantifier parser.
        $assignPattern = '\$verifyExit = \$LASTEXITCODE'
        $checkPattern = 'if \(\$verifyExit -ne 0\) \{[\s\S]{0,80}?throw'
        $Script:ScriptContent | Should -Match $assignPattern
        $Script:ScriptContent | Should -Match $checkPattern
    }
}

Describe 'bundle-python.ps1: python38._pth config (v0.4.3-alpha.2 backend timeout fix)' {

    It 'uncomments #import site so site-packages loads' {
        # Without `import site`, fastapi/uvicorn/PyYAML (all in site-packages)
        # are unreachable on Win7 LTS embedded Python.
        $Script:ScriptContent | Should -Match '(?m)^import site\s*$'
        $Script:ScriptContent | Should -Not -Match '(?m)^#import site\s*$'
    }

    It 'writes the resources/ parent path (`..`) into _pth so embedded Python can import backend.* and sage_core' {
        # Python's import system walks sys.path looking for the package name
        # as a DIRECTORY inside each entry. So sys.path must contain the
        # PARENT of the package directory, NOT the package itself. Writing
        # `..\backend` (==resources/backend/) makes Python look for
        # resources/backend/backend/ which doesn't exist — the v0.4.3-alpha.2
        # first-attempt bug that this test now guards against. Correct path:
        # `..` (==resources/) — finds both resources/backend/ and
        # resources/sage-core/ as children.
        $Script:ScriptContent | Should -Match '\$CanonicalResources\s*=\s*''\.{2}'''
        $pattern = '(?s)\$PthFile.*?Set-Content.*?\.\.'
        $Script:ScriptContent | Should -Match $pattern
    }

    It 'does NOT write ..\backend or ..\sage-core into _pth (would put package dir itself on sys.path, breaking imports)' {
        # Regression guard for the v0.4.3-alpha.2 first-attempt bug. Adding
        # the package directory itself to sys.path makes Python look for
        # <pkg>/<pkg>/ — ModuleNotFoundError.
        $Script:ScriptContent | Should -Not -Match '\.\.\\\\backend'
        $Script:ScriptContent | Should -Not -Match '\.\.\\\\sage-core'
    }

    It 'makes _pth config idempotent (re-running bundle does not duplicate the .. line)' {
        # Guard against repeated bundle runs appending duplicate `..` lines.
        # Use single quotes so PowerShell doesn't interpret \$CanonicalResources
        # as a variable interpolation (which would compile to an illegal
        # regex pattern ending with a stray backslash).
        $Script:ScriptContent | Should -Match 'Where-Object.*-ne \$CanonicalResources'
    }

    It 'verify step imports backend.main (catches _pth path errors at bundle time)' {
        # The original verify only imported fastapi/pydantic/jieba — all in
        # site-packages — so a missing _pth backend path was never caught.
        # Without `import backend.main` in the verify, the v0.4.3-alpha.1
        # Win7 bug would silently ship again.
        $Script:ScriptContent | Should -Match 'import backend\.main'
        $pattern = '(?s)import backend\.main.*?if \(\$verifyExit -ne 0\)'
        $Script:ScriptContent | Should -Match $pattern
    }
}

Describe 'bundle-python.ps1: dead-code cleanup' {

    It 'does not generate start-backend.bat (dead code, removed)' {
        # start-backend.bat was bundled into the NSIS installer but
        # electron/main.ts spawns python.exe directly — it was never called.
        $Script:ScriptContent | Should -Not -Match 'start-backend\.bat'
    }

    It 'does not write the @echo off batch script block' {
        $Script:ScriptContent | Should -Not -Match '"%~dp0python\\python\.exe" -m uvicorn'
    }
}

Describe 'bundle-python.ps1: requirements pin' {

    It 'references backend/requirements-py38.txt' {
        $Script:ScriptContent | Should -Match 'requirements-py38\.txt'
    }
}

Describe 'requirements-py38.txt: Python 3.8 compatibility pin' {

    BeforeAll {
        $Script:ReqPath = Join-Path $PSScriptRoot '..\backend\requirements-py38.txt'
        if (-not (Test-Path $Script:ReqPath)) {
            throw "Cannot find requirements-py38.txt at $Script:ReqPath"
        }
        $Script:ReqContent = Get-Content -Path $Script:ReqPath -Raw
    }

    It 'pins prometheus-client to a Python 3.8-compatible version (<=0.21.1)' {
        # 0.22.0+ require Python >=3.9 per PyPI metadata. On Win7 LTS we
        # bundle Python 3.8.10 embeddable, so 0.21.1 is the latest acceptable.
        $Script:ReqContent | Should -Match 'prometheus-client==0\.(?:2[01]|1)\.\d+'
        $Script:ReqContent | Should -Not -Match 'prometheus-client==0\.2[2-9]\.'
        $Script:ReqContent | Should -Not -Match 'prometheus-client==0\.2[2-9](?!\.)'
    }
}

Describe 'electron-builder.yml: NSIS extraResources cleanup' {

    BeforeAll {
        $Script:YmlPath = Join-Path $PSScriptRoot '..\electron-builder.yml'
        if (-not (Test-Path $Script:YmlPath)) {
            throw "Cannot find electron-builder.yml at $Script:YmlPath"
        }
        $Script:YmlContent = Get-Content -Path $Script:YmlPath -Raw
    }

    It 'does not bundle start-backend.bat as an NSIS extraResource' {
        # Pair with the bundle-python.ps1 cleanup test above.
        $Script:YmlContent | Should -Not -Match 'resources/start-backend\.bat'
    }
}
