param([switch]$Install, [string]$AppDirectory)

$ErrorActionPreference = 'Stop'
$probe = 'import sys, tkinter as tk; assert sys.version_info >= (3, 10); root = tk.Tk(); root.withdraw(); root.destroy(); print(sys.executable)'

function Find-CompanionPython {
    $standard = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    $candidates = @(
        (Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue).Source
        (Get-ChildItem "$standard\Python3*\python.exe" -File -ErrorAction SilentlyContinue).FullName
        (Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue).Source
    ) | Where-Object { $_ } | Select-Object -Unique
    foreach ($candidate in $candidates) {
        # Windows' empty Store alias opens a storefront when launched without an interpreter.
        if ($candidate -like '*\Microsoft\WindowsApps\python.exe' -and
            -not (Get-AppxPackage -Name 'PythonSoftwareFoundation.Python*' -ErrorAction SilentlyContinue)) { continue }
        $flags = @()
        if ([IO.Path]::GetFileName($candidate) -eq 'py.exe') { $flags += '-3' }
        try {
            $interpreter = & $candidate @flags -E -c $probe 2>$null
            if ($LASTEXITCODE -eq 0 -and $interpreter -and (Test-Path -LiteralPath $interpreter -PathType Leaf)) {
                return $interpreter
            }
        } catch { continue }
    }
}

function Install-CompanionPython {
    $version = '3.13.17'
    $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    switch ($arch) {
        'AMD64' { $suffix = '-amd64'; $digest = '5da012101ba2e17113a9a1cd901e9ce1441086f2b7ecb5de06ec94163899a190' }
        'ARM64' { $suffix = '-arm64'; $digest = '3089a1977c32b26f5078e5a7d0285b7a861b8c96250c5dac3b6af59fbe9e9a75' }
        'x86'   { $suffix = '';       $digest = '91cd5b0293162e11c5599f80dc5bd14658cf086c8234a3117b58cfcb93c4eff3' }
        default { throw "Unbekannte Windows-Architektur: $arch" }
    }
    $uri = "https://www.python.org/ftp/python/$version/python-$version$suffix.exe"
    $download = Join-Path ([IO.Path]::GetTempPath()) ("poe2-python-{0}.exe" -f [guid]::NewGuid())
    try {
        Write-Host "Lade Python $version mit Tcl/Tk fuer dein Windows-Benutzerkonto ..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $uri -UseBasicParsing -OutFile $download
        if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne $digest) {
            throw 'Die heruntergeladene Datei stimmt nicht mit der von python.org veroeffentlichten Pruefsumme ueberein.'
        }
        $options = '/passive InstallAllUsers=0 Include_tcltk=1 Include_launcher=0 PrependPath=0 Include_test=0'
        $process = Start-Process -FilePath $download -ArgumentList $options -Wait -PassThru
        if ($process.ExitCode -notin @(0, 3010)) { throw "Python-Setup meldet Fehler $($process.ExitCode)." }
    } finally {
        if (Test-Path -LiteralPath $download) { Remove-Item -LiteralPath $download }
    }
}

try {
    $python = Find-CompanionPython
    if (-not $python -and $Install) {
        Install-CompanionPython
        $python = Find-CompanionPython
    }
    if (-not $python) { throw 'Python 3.10+ mit Tcl/Tk fehlt. Oeffne "Voraussetzungen installieren.cmd".' }
    if ($Install) {
        Write-Host "Python und Tcl/Tk funktionieren: $python"
        Write-Host 'Du kannst jetzt "PoE2 Guide starten.cmd" oeffnen.'
    } else {
        $guide = Join-Path $AppDirectory 'poe2_standalone_overlay.py'
        $windowed = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
        if (Test-Path -LiteralPath $windowed) {
            Start-Process -FilePath $windowed -ArgumentList ('-E -B "{0}"' -f $guide)
        } else {
            & $python -E -B $guide
            exit $LASTEXITCODE
        }
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
