<#
.SYNOPSIS
  ecourt-cli 의 .env 값을 채우고 수정하는 셋업 도구.

.DESCRIPTION
  - 인자 없이 실행      : 대화형으로 모든 값을 입력/수정 (Enter 시 기존값 유지)
  - -Show              : 현재 .env 값 출력 (비밀번호/토큰은 마스킹/암호화표시)
  - -Set "KEY=VALUE"   : 특정 값만 비대화형으로 수정 (여러 개 가능)
  - -ListCerts         : PC 에서 발견된 공동인증서(NPKI) 목록만 출력

  비밀번호/토큰은 Windows DPAPI 로 암호화하여 KEY_ENC 형태로 저장합니다
  (평문 저장 안 함). 암호화에는 .venv 파이썬 + secret_store.py 가 필요합니다.

.EXAMPLE
  .\setup_env.ps1
  .\setup_env.ps1 -Show
  .\setup_env.ps1 -Set "TELEGRAM_CHAT_ID=12345","SYNC_TIME=09:00"
  .\setup_env.ps1 -ListCerts
#>
[CmdletBinding()]
param(
  [string[]]$Set,
  [switch]$Show,
  [switch]$ListCerts
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvPath   = Join-Path $ScriptDir '.env'

# DPAPI 로 암호화 저장하는 비밀 키 (저장 시 KEY_ENC 로 보관)
$SECRET_KEYS = @('ECFS_CERT_PW', 'TELEGRAM_BOT_TOKEN')

function Read-EnvFile([string]$path) {
  $h = @{}
  if (Test-Path $path) {
    foreach ($line in [System.IO.File]::ReadAllLines($path)) {
      if ($line -match '^\s*#') { continue }
      if ($line -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$') {
        $val = ($matches[2] -replace '\s+#.*$', '').Trim()
        $h[$matches[1]] = $val
      }
    }
  }
  return $h
}

function ConvertFrom-SecurePlain($sec) {
  if ($null -eq $sec) { return '' }
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
  try   { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Mask([string]$v) {
  if ([string]::IsNullOrEmpty($v)) { return '(미설정)' }
  if ($v.Length -le 4) { return '****' }
  return ('*' * ($v.Length - 4)) + $v.Substring($v.Length - 4)
}

function Get-VenvPython {
  $p = Join-Path $ScriptDir '.venv\Scripts\python.exe'
  if (Test-Path $p) { return $p }
  $c = Get-Command python -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  return $null
}

# 평문 -> DPAPI 암호문(base64). 실패 시 ok=$false.
function Protect-Secret([string]$plain) {
  $py = Get-VenvPython
  if (-not $py) { return @{ ok = $false } }
  $env:_ECOURT_SECRET_IN = $plain
  $b64 = $null
  try   { $b64 = & $py (Join-Path $ScriptDir 'secret_store.py') 'encrypt-env' }
  catch { $b64 = $null }
  finally { Remove-Item Env:\_ECOURT_SECRET_IN -ErrorAction SilentlyContinue }
  if ([string]::IsNullOrWhiteSpace($b64)) { return @{ ok = $false } }
  return @{ ok = $true; value = (($b64 | Out-String).Trim()) }
}

# 비밀값을 $v 에 설정 (암호화되면 KEY_ENC, 실패하면 평문 KEY)
function Set-SecretValue([hashtable]$v, [string]$key, [string]$plain) {
  $r = Protect-Secret $plain
  if ($r.ok) {
    $v["${key}_ENC"] = $r.value
    $v.Remove($key) | Out-Null
    Write-Host "  $key 암호화 저장(DPAPI)" -ForegroundColor Green
  } else {
    Write-Host "  [경고] 암호화 도구(.venv 파이썬) 없음 → 평문 저장됨: $key" -ForegroundColor Yellow
    $v[$key] = $plain
    $v.Remove("${key}_ENC") | Out-Null
  }
}

function Find-Certs {
  $roots = @()
  foreach ($sub in @('AppData\LocalLow\NPKI','AppData\Roaming\NPKI','AppData\Local\NPKI','Documents\NPKI')) {
    $roots += (Join-Path $env:USERPROFILE $sub)
  }
  foreach ($d in [char[]]([char]'A'..[char]'Z')) { $roots += "${d}:\NPKI"; $roots += "${d}:\GPKI" }
  $roots += 'C:\Program Files\NPKI','C:\Program Files (x86)\NPKI'

  $found = @()
  foreach ($root in $roots) {
    if (-not (Test-Path $root)) { continue }
    $userDirs = @()
    Get-ChildItem $root -Directory -ErrorAction SilentlyContinue | ForEach-Object {
      $u = Join-Path $_.FullName 'USER'; if (Test-Path $u) { $userDirs += $u }
    }
    $ru = Join-Path $root 'USER'; if (Test-Path $ru) { $userDirs += $ru }
    foreach ($u in $userDirs) {
      Get-ChildItem $u -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $der = Join-Path $_.FullName 'signCert.der'
        $key = Join-Path $_.FullName 'signPri.key'
        if ((Test-Path $der) -and (Test-Path $key)) {
          $nm = ''; if ($_.Name -match 'cn=([^()]+)') { $nm = $matches[1].Trim() }
          $sn = ''; if ($_.Name -match '(\d{12,})')   { $sn = $matches[1] }
          $found += [pscustomobject]@{ Name = $nm; Serial = $sn; Path = $_.FullName }
        }
      }
    }
  }
  return $found
}

function Write-EnvFile([hashtable]$v) {
  function Line([string]$key) {
    if ($v.ContainsKey($key) -and $null -ne $v[$key]) { return "$key=$($v[$key])" }
    return "$key="
  }
  # 비밀키: KEY_ENC 우선, 없으면 평문 KEY, 둘 다 없으면 주석
  function SecretLines([string]$key, [string]$comment) {
    $out = @($comment)
    if ($v["${key}_ENC"]) {
      $out += "${key}_ENC=$($v["${key}_ENC"])"
    } elseif ($v[$key]) {
      $out += '# (주의) 아래는 평문입니다. .venv 파이썬으로 setup 재실행 시 자동 암호화됩니다.'
      $out += "$key=$($v[$key])"
    } else {
      $out += "# ${key}_ENC="
    }
    return $out
  }

  $L = @()
  $L += '# ─── 전자소송(ecfs) 로그인 ────────────────────────────────'
  $L += '# 전자소송 사이트(ecfs.scourt.go.kr) 사용자 ID'
  $L += (Line 'ECFS_USER_ID'); $L += ''
  $L += (SecretLines 'ECFS_CERT_PW' '# 공동인증서 비밀번호 (DPAPI 암호화: ECFS_CERT_PW_ENC)'); $L += ''
  $L += '# 인증서 목록에서 선택할 이름 (보통 본인 성명 또는 법인명).'
  $L += (Line 'ECFS_CERT_NAME'); $L += ''
  $L += '# 인증서 저장 위치 탭 (브라우저 / 인증서찾기 / 하드디스크 / 이동식디스크 / 스마트인증)'
  $L += (Line 'ECFS_CERT_STORAGE'); $L += ''
  $L += '# (자동 폴백) 브라우저 탭에 인증서가 없을 때 ''인증서찾기''로 자동 등록할 NPKI 위치.'
  $L += '# ECFS_CERT_DIR(폴더 전체경로) 또는 ECFS_CERT_SERIAL(시리얼 일부) 중 하나.'
  if ($v['ECFS_CERT_DIR'])    { $L += (Line 'ECFS_CERT_DIR') }    else { $L += '# ECFS_CERT_DIR=' }
  if ($v['ECFS_CERT_SERIAL']) { $L += (Line 'ECFS_CERT_SERIAL') } else { $L += '# ECFS_CERT_SERIAL=' }
  $L += ''
  $L += '# ─── 사건 폴더 ────────────────────────────────────────────'
  $L += '# 다운로드한 사건기록을 저장할 루트 디렉토리 (클라우드 동기화 폴더 권장).'
  $L += (Line 'ECOURT_CASES_DIR'); $L += ''
  $L += '# ─── 텔레그램 알림 ────────────────────────────────────────'
  $L += (SecretLines 'TELEGRAM_BOT_TOKEN' '# @BotFather 봇 토큰 (DPAPI 암호화: TELEGRAM_BOT_TOKEN_ENC)'); $L += ''
  $L += '# 알림 받을 채팅 ID'
  $L += (Line 'TELEGRAM_CHAT_ID'); $L += ''
  $L += '# ─── 데몬 스케줄 ──────────────────────────────────────────'
  $L += '# 매일 실행 시각 (24h, HH:MM)'
  $L += (Line 'SYNC_TIME')

  if (Test-Path $EnvPath) { Copy-Item $EnvPath "$EnvPath.bak" -Force }
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($EnvPath, ($L -join "`r`n") + "`r`n", $enc)
}

function Secret-Status([hashtable]$v, [string]$key) {
  if ($v["${key}_ENC"]) { return '(DPAPI 암호화됨)' }
  if ($v[$key])         { return (Mask $v[$key]) + ' (평문!)' }
  return '(미설정)'
}

# ─────────────────────────────────────────────────────────────
$cur = Read-EnvFile $EnvPath

if ($ListCerts) {
  $certs = Find-Certs
  if (-not $certs) { Write-Host '발견된 공동인증서(NPKI) 없음' -ForegroundColor Yellow; return }
  $i = 0; $certs | ForEach-Object { Write-Host ("[{0}] {1}  (serial {2})`n     {3}" -f $i, $_.Name, $_.Serial, $_.Path); $i++ }
  return
}

if ($Show) {
  Write-Host "현재 .env ($EnvPath)" -ForegroundColor Cyan
  $order = @('ECFS_USER_ID','ECFS_CERT_PW','ECFS_CERT_NAME','ECFS_CERT_STORAGE',
             'ECFS_CERT_DIR','ECFS_CERT_SERIAL','ECOURT_CASES_DIR',
             'TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID','SYNC_TIME')
  foreach ($k in $order) {
    if ($SECRET_KEYS -contains $k) { $val = Secret-Status $cur $k }
    elseif ([string]::IsNullOrEmpty($cur[$k])) { $val = '(미설정)' }
    else { $val = $cur[$k] }
    Write-Host ("  {0,-20} = {1}" -f $k, $val)
  }
  return
}

if ($Set) {
  foreach ($pair in $Set) {
    $idx = $pair.IndexOf('=')
    if ($idx -lt 1) { Write-Host "잘못된 형식(무시): $pair" -ForegroundColor Yellow; continue }
    $k = $pair.Substring(0, $idx).Trim()
    $val = $pair.Substring($idx + 1)
    if ($SECRET_KEYS -contains $k) { Set-SecretValue $cur $k $val }
    else { $cur[$k] = $val; Write-Host "설정: $k" -ForegroundColor Green }
  }
  Write-EnvFile $cur
  Write-Host ".env 저장 완료 (백업: .env.bak)" -ForegroundColor Green
  return
}

# ── 대화형 모드 ──────────────────────────────────────────────
function Ask([string]$desc, [string]$current, [string]$default, [bool]$secret) {
  if ($current) { $shown = $current } elseif ($default) { $shown = $default } else { $shown = '(미설정)' }
  $inp = Read-Host "$desc [$shown] (Enter=유지)"
  if ([string]::IsNullOrEmpty($inp)) { if ($current) { return $current } else { return $default } }
  return $inp
}

function Ask-Secret([hashtable]$v, [string]$key, [string]$desc) {
  $has = $v.ContainsKey("${key}_ENC") -or $v.ContainsKey($key)
  $shown = if ($has) { '(설정됨)' } else { '(미설정)' }
  $sec = Read-Host "$desc [$shown] (Enter=유지)" -AsSecureString
  $plain = ConvertFrom-SecurePlain $sec
  if (-not [string]::IsNullOrEmpty($plain)) { Set-SecretValue $v $key $plain }
}

Write-Host '=== ecourt-cli .env 셋업 (Enter 누르면 기존값 유지) ===' -ForegroundColor Cyan
Write-Host '── 전자소송 로그인 ──' -ForegroundColor DarkCyan
$cur['ECFS_USER_ID']      = Ask '전자소송 사용자 ID'        $cur['ECFS_USER_ID']      ''       $false
Ask-Secret $cur 'ECFS_CERT_PW' '공동인증서 비밀번호'
$cur['ECFS_CERT_NAME']    = Ask '인증서 이름(본인 성명/법인)' $cur['ECFS_CERT_NAME']   ''       $false
$cur['ECFS_CERT_STORAGE'] = Ask '인증서 저장 위치 탭'        $cur['ECFS_CERT_STORAGE'] '브라우저' $false

Write-Host '── 인증서 자동 검색 ──' -ForegroundColor DarkCyan
$doFind = Read-Host '이 PC 의 공동인증서를 검색해서 선택할까요? (Y/n)'
if ($doFind -ne 'n' -and $doFind -ne 'N') {
  $certs = Find-Certs
  if (-not $certs) {
    Write-Host '  발견된 인증서 없음 (USB 라면 꽂은 뒤 다시 실행).' -ForegroundColor Yellow
  } else {
    $nameF = $cur['ECFS_CERT_NAME']
    $ordered = @()
    if ($nameF) { $ordered += ($certs | Where-Object { $_.Name -like "*$nameF*" }) }
    $ordered += ($certs | Where-Object { -not ($ordered -contains $_) })
    $i = 0
    foreach ($c in $ordered) { Write-Host ("  [{0}] {1}  (serial {2})`n       {3}" -f $i, $c.Name, $c.Serial, $c.Path); $i++ }
    $pick = Read-Host '번호 선택 (건너뛰려면 Enter)'
    if ($pick -match '^\d+$' -and [int]$pick -lt $ordered.Count) {
      $sel = $ordered[[int]$pick]
      $cur['ECFS_CERT_DIR']    = $sel.Path
      $cur['ECFS_CERT_SERIAL'] = $sel.Serial
      Write-Host "  선택: $($sel.Name)" -ForegroundColor Green
    }
  }
}

Write-Host '── 저장 폴더 ──' -ForegroundColor DarkCyan
$cur['ECOURT_CASES_DIR'] = Ask '사건기록 저장 폴더'  $cur['ECOURT_CASES_DIR'] '' $false

Write-Host '── 텔레그램 알림 (선택, 없으면 Enter) ──' -ForegroundColor DarkCyan
Ask-Secret $cur 'TELEGRAM_BOT_TOKEN' '텔레그램 봇 토큰'
$cur['TELEGRAM_CHAT_ID'] = Ask '텔레그램 채팅 ID'  $cur['TELEGRAM_CHAT_ID'] '' $false

Write-Host '── 스케줄 ──' -ForegroundColor DarkCyan
$cur['SYNC_TIME'] = Ask '매일 실행 시각(HH:MM)'  $cur['SYNC_TIME'] '18:03' $false

Write-EnvFile $cur
Write-Host "`n.env 저장 완료 (백업: .env.bak)" -ForegroundColor Green
Write-Host '확인: .\setup_env.ps1 -Show' -ForegroundColor DarkGray
