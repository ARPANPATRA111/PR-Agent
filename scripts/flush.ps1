# Weekly Progress Agent - Data Flush Script
# WARNING: This will DELETE ALL DATA in the application!
# Use before production deployment to start fresh.

param(
    [switch]$Force,
    [switch]$KeepLogs,
    [switch]$DryRun
)

Write-Host "========================================" -ForegroundColor Red
Write-Host "  Weekly Progress Agent - DATA FLUSH" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red
Write-Host ""

# Determine project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
if (-not $ProjectRoot -or -not (Test-Path $ProjectRoot)) {
    $ProjectRoot = "b:\Public Repository\weekly_agent"
}

$BackendDataDir = Join-Path $ProjectRoot "backend\data"

Write-Host "Project Root: $ProjectRoot" -ForegroundColor Yellow
Write-Host "Data Directory: $BackendDataDir" -ForegroundColor Yellow
Write-Host ""

if ($DryRun) {
    Write-Host "[DRY RUN MODE] No actual deletions will occur." -ForegroundColor Cyan
    Write-Host ""
}

# List what will be deleted
Write-Host "The following will be DELETED:" -ForegroundColor Red
Write-Host ""

$itemsToDelete = @()

# SQLite database
$dbPath = Join-Path $BackendDataDir "weekly_agent.db"
$dbWalPath = Join-Path $BackendDataDir "weekly_agent.db-wal"
$dbShmPath = Join-Path $BackendDataDir "weekly_agent.db-shm"

if (Test-Path $dbPath) {
    Write-Host "  [x] SQLite Database: $dbPath" -ForegroundColor Yellow
    $itemsToDelete += $dbPath
}
if (Test-Path $dbWalPath) {
    Write-Host "  [x] SQLite WAL: $dbWalPath" -ForegroundColor Yellow
    $itemsToDelete += $dbWalPath
}
if (Test-Path $dbShmPath) {
    Write-Host "  [x] SQLite SHM: $dbShmPath" -ForegroundColor Yellow
    $itemsToDelete += $dbShmPath
}

# ChromaDB
$chromaPath = Join-Path $BackendDataDir "chroma"
if (Test-Path $chromaPath) {
    Write-Host "  [x] ChromaDB Vector Store: $chromaPath" -ForegroundColor Yellow
    $itemsToDelete += $chromaPath
}

# Audio temp files
$audioPath = Join-Path $BackendDataDir "audio_temp"
if (Test-Path $audioPath) {
    $audioFiles = Get-ChildItem $audioPath -File -ErrorAction SilentlyContinue
    $audioCount = ($audioFiles | Measure-Object).Count
    Write-Host "  [x] Audio Temp Files: $audioCount files" -ForegroundColor Yellow
    $itemsToDelete += $audioPath
}

# Backups
$backupPath = Join-Path $BackendDataDir "backups"
if (Test-Path $backupPath) {
    $backupFiles = Get-ChildItem $backupPath -File -ErrorAction SilentlyContinue
    $backupCount = ($backupFiles | Measure-Object).Count
    Write-Host "  [x] Backup Files: $backupCount files" -ForegroundColor Yellow
    $itemsToDelete += $backupPath
}

# Logs (optional)
$logsPath = Join-Path $BackendDataDir "logs"
if (Test-Path $logsPath) {
    if ($KeepLogs) {
        Write-Host "  [ ] Logs: KEEPING (--KeepLogs specified)" -ForegroundColor Green
    } else {
        $logFiles = Get-ChildItem $logsPath -File -ErrorAction SilentlyContinue
        $logCount = ($logFiles | Measure-Object).Count
        Write-Host "  [x] Log Files: $logCount files" -ForegroundColor Yellow
        $itemsToDelete += $logsPath
    }
}

Write-Host ""

if ($itemsToDelete.Count -eq 0) {
    Write-Host "Nothing to delete. Data directory is clean." -ForegroundColor Green
    exit 0
}

# Confirmation
if (-not $Force -and -not $DryRun) {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  THIS ACTION CANNOT BE UNDONE!" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Type 'FLUSH' to confirm deletion: " -ForegroundColor Yellow -NoNewline
    $confirmation = Read-Host
    
    if ($confirmation -ne "FLUSH") {
        Write-Host ""
        Write-Host "Aborted. No data was deleted." -ForegroundColor Green
        exit 0
    }
}

if ($DryRun) {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  DRY RUN COMPLETE" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Run without -DryRun to actually delete files." -ForegroundColor Yellow
    exit 0
}

# Perform deletion
Write-Host ""
Write-Host "Deleting data..." -ForegroundColor Yellow
Write-Host ""

$deletedCount = 0
$failedCount = 0

foreach ($item in $itemsToDelete) {
    if (Test-Path $item) {
        try {
            if ((Get-Item $item).PSIsContainer) {
                # It's a directory - clear contents but keep directory
                Remove-Item "$item\*" -Recurse -Force -ErrorAction Stop
                Write-Host "  [OK] Cleared: $item" -ForegroundColor Green
            } else {
                # It's a file
                Remove-Item $item -Force -ErrorAction Stop
                Write-Host "  [OK] Deleted: $item" -ForegroundColor Green
            }
            $deletedCount++
        } catch {
            Write-Host "  [FAIL] $item - $($_.Exception.Message)" -ForegroundColor Red
            $failedCount++
        }
    }
}

# Recreate empty directories
$dirsToRecreate = @(
    (Join-Path $BackendDataDir "chroma"),
    (Join-Path $BackendDataDir "audio_temp"),
    (Join-Path $BackendDataDir "backups"),
    (Join-Path $BackendDataDir "logs")
)

foreach ($dir in $dirsToRecreate) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  [OK] Recreated: $dir" -ForegroundColor Cyan
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  FLUSH COMPLETE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Deleted: $deletedCount items" -ForegroundColor White
if ($failedCount -gt 0) {
    Write-Host "Failed:  $failedCount items" -ForegroundColor Red
}
Write-Host ""
Write-Host "The application will start fresh on next run." -ForegroundColor Yellow
Write-Host ""

# Usage info
Write-Host "Usage:" -ForegroundColor Cyan
Write-Host "  .\flush.ps1              # Interactive mode with confirmation" -ForegroundColor Gray
Write-Host "  .\flush.ps1 -Force       # Skip confirmation (for scripts)" -ForegroundColor Gray
Write-Host "  .\flush.ps1 -KeepLogs    # Keep log files" -ForegroundColor Gray
Write-Host "  .\flush.ps1 -DryRun      # Preview what will be deleted" -ForegroundColor Gray
Write-Host ""
