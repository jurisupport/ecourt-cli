<#
  ecourt-cli 원클릭 설치 스크립트 (Windows PowerShell)

  사용법 (PowerShell 한 줄):
    irm https://raw.githubusercontent.com/jurisupport/ecourt-cli/main/install.ps1 | iex

  하는 일:
    1) Python(3.10+) 없으면 winget 또는 python.org 설치 프로그램으로 자동 설치
    2) 소스 내려받기 (git 있으면 clone, 없으면 ZIP)
    3) 가상환경(.venv) + 의존성 + Playwright(Edge) 설치
    4) 이어서 환경설정(.env) 진행 여부 질의
#>
$ErrorActionPreference = 'Stop'

$RepoGit = 'https://github.com/jurisupport/ecourt-cli.git'
$RepoZip = 'https://github.com/jurisupport/ecourt-cli/archive/refs/heads/main.zip'
$Target  = Join-Path $HOME 'ecourt-cli'

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
  $m = [Environment]::GetEnvironmentVariable('Path','Machine')
  $u = [Environment]::GetEnvironmentVariable('Path','User')
  $env:Path = "$m;$u"
}
function Ensure-Tls12 {
  try { [Net.ServicePointManager]::SecurityProtocol =
          [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}
}
# winget 없이 python.org 설치 프로그램을 직접 받아 조용히 설치 (사용자 권한)
function Install-PythonViaInstaller {
  Ensure-Tls12
  $ver = '3.12.8'
  $url = "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe"
  $exe = Join-Path $env:TEMP "python-$ver-amd64.exe"
  try {
    Write-Host "      -> python.org 에서 Python $ver 다운로드..." -ForegroundColor Yellow
    Invoke-WebRequest $url -OutFile $exe -UseBasicParsing
    Write-Host '      -> 설치 중(조용히, 1~2분)...' -ForegroundColor Yellow
    Start-Process -FilePath $exe -Wait -ArgumentList `
      '/quiet','InstallAllUsers=0','PrependPath=1','Include_pip=1','Include_launcher=1' | Out-Null
    Remove-Item $exe -ErrorAction SilentlyContinue
    Refresh-Path
    return $true
  } catch {
    Write-Host "      설치 프로그램 실행 실패: $($_.Exception.Message)" -ForegroundColor Red
    return $false
  }
}

Write-Host ''
Write-Host '====== ecourt-cli 설치 시작 ======' -ForegroundColor Cyan

# 1) Python (3.10+ 필요) ---------------------------------------------------
function Get-PyVersion {
  try {
    $raw = (& python --version) 2>&1
    if ($raw -match '(\d+)\.(\d+)(\.(\d+))?') { return [version]("{0}.{1}" -f $matches[1], $matches[2]) }
  } catch {}
  return $null
}
function Py-OK { $v = Get-PyVersion; return ($null -ne $v -and $v -ge [version]'3.10') }

if (-not (Py-OK)) {
  $cur = Get-PyVersion
  if (Have python) { Write-Host "[1/4] Python 버전 부족(현재 $cur, 3.10+ 필요) -> 자동 설치" -ForegroundColor Yellow }
  else             { Write-Host '[1/4] Python 미설치 -> 자동 설치를 시도합니다' -ForegroundColor Yellow }
  if (Have winget) {
    Write-Host '      -> winget 으로 Python 3.12 설치/업그레이드...' -ForegroundColor Yellow
    try { winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements } catch {}
    Refresh-Path
    if (-not (Py-OK)) { Install-PythonViaInstaller | Out-Null }   # winget 실패 시 직접 설치
  } else {
    Install-PythonViaInstaller | Out-Null                          # winget 없으면 바로 직접 설치
  }
}
if (-not (Py-OK)) {
  Write-Host ''
  Write-Host 'Python 3.10+ 자동 설치에 실패했습니다.' -ForegroundColor Red
  Write-Host '  방법 1) https://www.python.org/downloads/ 에서 설치 (설치화면에서 "Add Python to PATH" 체크)' -ForegroundColor Yellow
  Write-Host '  방법 2) 설치 후 PowerShell 을 새로 열고 아래 한 줄을 다시 실행하세요:' -ForegroundColor Yellow
  Write-Host '    irm https://raw.githubusercontent.com/jurisupport/ecourt-cli/main/install.ps1 | iex' -ForegroundColor Gray
  return
}
Write-Host "[1/4] Python OK ($(python --version 2>&1))" -ForegroundColor Green

# 2) 소스 내려받기 ----------------------------------------------------------
if (Test-Path $Target) {
  Write-Host "[2/4] 기존 폴더 발견: $Target" -ForegroundColor Yellow
  if ((Have git) -and (Test-Path (Join-Path $Target '.git'))) { git -C $Target pull --ff-only }
} elseif (Have git) {
  Write-Host '[2/4] git clone ...' -ForegroundColor Yellow
  git clone $RepoGit $Target
} else {
  Write-Host '[2/4] git 없음 → ZIP 다운로드 ...' -ForegroundColor Yellow
  $tmp = Join-Path $env:TEMP 'ecourt-cli.zip'
  Invoke-WebRequest $RepoZip -OutFile $tmp
  Expand-Archive $tmp -DestinationPath $HOME -Force
  Move-Item (Join-Path $HOME 'ecourt-cli-main') $Target -Force
  Remove-Item $tmp -Force
}
Set-Location $Target
Write-Host "[2/4] 소스 준비 완료: $Target" -ForegroundColor Green

# 3) venv + 의존성 ----------------------------------------------------------
Write-Host '[3/4] 가상환경 + 라이브러리 설치 (몇 분 걸릴 수 있습니다)...' -ForegroundColor Yellow
$py = Join-Path $Target '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { python -m venv .venv }
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt
& $py -m playwright install msedge
Write-Host '[3/4] 라이브러리 설치 완료' -ForegroundColor Green

# 4) 환경설정 ---------------------------------------------------------------
Write-Host ''
Write-Host '====== 설치 완료! ======' -ForegroundColor Cyan
Write-Host "폴더: $Target"
Write-Host ''
$go = Read-Host '이어서 환경설정(.env: 아이디/인증서/저장폴더)을 진행할까요? (Y/n)'
if ($go -ne 'n' -and $go -ne 'N') {
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Target 'setup_env.ps1')
} else {
  Write-Host '나중에 아래 명령으로 설정하세요:' -ForegroundColor Yellow
  Write-Host "  cd `"$Target`""
  Write-Host '  powershell -ExecutionPolicy Bypass -File .\setup_env.ps1'
}
Write-Host ''
Write-Host '첫 실행(한 건 받아보기 → 성공하면 전체 다운로드 여부를 물어봅니다):' -ForegroundColor DarkGray
Write-Host "  cd `"$Target`"; .\.venv\Scripts\python.exe ecourt_download.py --case 0"
Write-Host ''
Write-Host '함께 쓰면 좋은 쥬리서포트 도구:' -ForegroundColor Cyan
Write-Host '  - jurisupport-plugins (Claude Code 법률 자동화: 사건요약/쟁점/서면 초안)'
Write-Host '      irm https://raw.githubusercontent.com/jurisupport/jurisupport-plugins/main/windows-bootstrap.ps1 | iex'
Write-Host '  - legal-terminal (소송 변호사용 올인원 AI 작업공간)'
Write-Host '      irm https://raw.githubusercontent.com/jurisupport/legal-terminal/main/install.ps1 | iex'
Write-Host '  - https://jurisupport.com'
