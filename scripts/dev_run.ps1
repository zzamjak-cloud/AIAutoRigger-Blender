# Windows 포터블 Blender 격리 개발 프로필 실행기.
# 프로젝트 전용 포터블 Blender 의 portable\extensions\user_default\<id> 만 저장소 Junction 으로 연결한다.
#
# 사용 예:
#   scripts\dev_run.ps1                                   # GUI
#   scripts\dev_run.ps1 -LinkOnly                         # Junction 만 갱신
#   scripts\dev_run.ps1 -Background -PythonFile tests\blender_smoke.py
#   scripts\dev_run.ps1 -Background -PythonExpr "import bpy"
#   scripts\dev_run.ps1 -- --some-blender-arg             # 추가 인자 전달
#   (-b, -P 같은 Blender 단축 인자는 PowerShell 파라미터 접두 매칭과 충돌하므로 긴 형식을 쓴다)
#
# 환경 변수:
#   AIRIG_BLENDER_DIR  프로젝트 전용 포터블 Blender 디렉터리 (blender.exe 위치, 필수)
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$BlenderDir = $env:AIRIG_BLENDER_DIR,
    [switch]$LinkOnly,
    [switch]$Background,
    [string]$PythonExpr,
    [string]$PythonFile,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$BlenderArgs
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Message) {
    [Console]::Error.WriteLine("[dev_run] $Message")
    exit 1
}

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Manifest = Join-Path $RepoRoot 'blender_manifest.toml'
if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) {
    Fail "blender_manifest.toml 을 찾을 수 없습니다: $Manifest"
}

$AddonId = $null
foreach ($line in [System.IO.File]::ReadAllLines($Manifest, [System.Text.Encoding]::UTF8)) {
    if ($line -match '^id\s*=\s*"([A-Za-z0-9_]+)"') { $AddonId = $Matches[1]; break }
}
if (-not $AddonId) { Fail '매니페스트에서 id 를 읽지 못했습니다.' }

if (-not $BlenderDir) { Fail 'AIRIG_BLENDER_DIR 또는 -BlenderDir 로 프로젝트 전용 포터블 Blender 경로를 지정하세요.' }
$BlenderExe = Join-Path $BlenderDir 'blender.exe'
if (-not (Test-Path -LiteralPath $BlenderExe -PathType Leaf)) { Fail "blender.exe 가 없습니다: $BlenderExe" }

$ExtDir = Join-Path $BlenderDir 'portable\extensions\user_default'
$Link = Join-Path $ExtDir $AddonId
New-Item -ItemType Directory -Force -Path $ExtDir | Out-Null

$item = Get-Item -LiteralPath $Link -Force -ErrorAction SilentlyContinue
if ($item) {
    if ($item.LinkType -in @('Junction', 'SymbolicLink')) {
        $target = @($item.Target)[0]
        # 대상을 읽지 못한(끊어진) 링크도 재생성한다
        if (-not $target -or ([System.IO.Path]::GetFullPath([System.IO.Path]::Combine($ExtDir, $target)).TrimEnd('\') -ne $RepoRoot.TrimEnd('\'))) {
            # 링크 자체만 제거한다 (대상 디렉터리 내용은 건드리지 않음)
            [System.IO.Directory]::Delete($Link)
            $item = $null
        }
    } else {
        Fail "Junction 위치에 실제 폴더/파일이 있어 중단합니다: $Link"
    }
}
if (-not $item) {
    New-Item -ItemType Junction -Path $Link -Target $RepoRoot | Out-Null
}

$env:AIRIG_ADDON_ID = $AddonId
Write-Host "[dev_run] profile: $(Join-Path $BlenderDir 'portable')"
Write-Host "[dev_run] link:    $Link -> $RepoRoot"
if ($LinkOnly) { exit 0 }

$argList = @()
if ($Background) { $argList += '--background' }
$argList += @('--python-exit-code', '1', '--python', (Join-Path $RepoRoot 'scripts\dev_bootstrap.py'))
if ($PythonFile) { $argList += @('--python', (Resolve-Path -LiteralPath $PythonFile).Path) }
if ($PythonExpr) { $argList += @('--python-expr', $PythonExpr) }
if ($BlenderArgs) { $argList += ($BlenderArgs | Where-Object { $_ -ne '--' }) }

# PowerShell 5.1 은 네이티브 인자 속 큰따옴표를 이스케이프하지 않아 --python-expr 값이 깨진다
if ($PSVersionTable.PSVersion.Major -lt 7) {
    $argList = $argList | ForEach-Object { $_ -replace '"', '\"' }
}

& $BlenderExe @argList
exit $LASTEXITCODE
