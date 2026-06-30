<#
  ecourt-cli 원클릭 설치 스크립트 (Windows PowerShell)

  사용법 (PowerShell 한 줄):
    irm https://raw.githubusercontent.com/jurisupport/ecourt-cli/main/install.ps1 | iex

  하는 일:
    1) Python 없으면 winget 으로 설치
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

Write-Host ''
Write-Host '====== ecourt-cli 설치 시작 ======' -ForegroundColor Cyan

# 1) Python ----------------------------------------------------------------
if (-not (Have python)) {
  if (Have winget) {
    Write-Host '[1/4] Python 미설치 → winget 으로 설치합니다...' -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Refresh-Path
  } else {
    throw 'Python 과 winget 이 모두 없습니다. https://www.python.org/downloads/ 에서 Python 설치 후("Add Python to PATH" 체크) 다시 실행하세요.'
  }
}
if (-not (Have python)) {
  throw 'Python 설치 후 PATH 인식이 안 됩니다. PowerShell 창을 닫고 새로 연 뒤 설치 명령을 다시 실행하세요.'
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
Write-Host '첫 실행(한 건 받아보기):' -ForegroundColor DarkGray
Write-Host "  cd `"$Target`"; .\.venv\Scripts\python.exe ecourt_download.py --case 0"
