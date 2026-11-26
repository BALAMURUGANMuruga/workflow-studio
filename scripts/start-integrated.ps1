param([switch]$ChatOnly)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$requiredPorts = @(4200, 4300, 8000)
if (-not $ChatOnly) { $requiredPorts += @(8081, 9002, 9003) }
$busyPorts = foreach ($port in $requiredPorts) {
    $probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    try {
        $probe.Start()
    } catch [System.Net.Sockets.SocketException] {
        $port
    } finally {
        $probe.Stop()
    }
}
$checks = @{
    4200 = @{ Path='/operations/'; Marker='<base href="/operations/">' }
    4300 = @{ Path='/operations/'; Marker='<base href="/operations/">' }
    8000 = @{ Path='/openapi.json'; Marker='"title":"Workflow Studio API"' }
}
$reuse = @()
foreach ($port in $busyPorts) {
    $check = $checks[$port]
    if ($check) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 `
                -Uri ('http://127.0.0.1:{0}{1}' -f $port, $check.Path)
            if ($response.Content.Contains($check.Marker)) {
                $reuse += $port
                Write-Host "Reusing verified service on port $port."
                continue
            }
        } catch {
            Write-Verbose $_.Exception.Message
        }
    }
    throw "Port $port is in use by a service this launcher could not verify. Stop that process and rerun the launcher."
}

foreach ($name in @('python.exe', 'npm.cmd')) {
    Get-Command $name -ErrorAction Stop | Out-Null
}
if (-not $ChatOnly) {
    Get-Command 'mvn.cmd' -ErrorAction Stop | Out-Null
    $javaHome = $env:WORKFLOW_JAVA_HOME
    if (-not $javaHome) {
        $javaHome = Split-Path -Parent (Split-Path -Parent (Get-Command javac.exe -ErrorAction Stop).Source)
    }
    $javac = Join-Path $javaHome 'bin/javac.exe'
    $version = & $javac --version
    if ($version -notmatch '^javac (2[1-9]|[3-9][0-9])(?:\.|$)') {
        throw 'Set WORKFLOW_JAVA_HOME to a JDK 21 or later installation.'
    }
    $env:JAVA_HOME = $javaHome
}

if (-not $env:WORKFLOW_BRIDGE_TOKEN) {
    $env:WORKFLOW_BRIDGE_TOKEN = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
}

$logDir = Join-Path $workspace '.integrated-logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$services = @(
    @{ Name='studio-api'; Port=8000; Directory='backend'; Command='python -m uvicorn app.main:app --host 127.0.0.1 --port 8000' },
    @{ Name='portal'; Port=4300; Directory='operations/portal'; Command='npm.cmd start -- --host 127.0.0.1 --port 4300 --hmr=false' },
    @{ Name='studio'; Port=4200; Directory='frontend'; Command='npm.cmd start -- --port 4200' }
)
if (-not $ChatOnly) {
    $services += @(
        @{ Name='portal-service'; Port=9002; Directory='operations/portal-service'; Command='mvn.cmd spring-boot:run' },
        @{ Name='workflow-service'; Port=8081; Directory='operations/workflow-service'; Command='mvn.cmd spring-boot:run' },
        @{ Name='reprocess-service'; Port=9003; Directory='operations/reprocess-service'; Command='mvn.cmd spring-boot:run' }
    )
}

foreach ($service in $services) {
    if ($service.Port -in $reuse) { continue }
    $process = Start-Process -FilePath 'cmd.exe' -ArgumentList '/d', '/c', $service.Command `
        -WorkingDirectory (Join-Path $workspace $service.Directory) -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDir ($service.Name + '.log')) `
        -RedirectStandardError (Join-Path $logDir ($service.Name + '.error.log'))
    Write-Host "$($service.Name) PID $($process.Id)"
}
Write-Host 'Open http://127.0.0.1:4200/operations/ after the services finish starting.'
Write-Host "Logs: $logDir"
