param([Parameter(Mandatory=$true)][string]$Name, [string]$Extra = "")

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class U {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
}
"@

# bring a window to front even from a background process: ALT key toggle grants SetForegroundWindow rights
function Bring-To-Front([IntPtr]$h) {
    if ($h -eq [IntPtr]::Zero) { return }
    [U]::ShowWindow($h, 9) | Out-Null
    [U]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)   # ALT down
    [U]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)   # ALT up
    [U]::SetForegroundWindow($h) | Out-Null
    [U]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
    [U]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
}

# idempotent shortcut: window whose title contains $Name already on screen -> bring to front, return instantly
function Find-ExistingWindow([string]$sub) {
    if (-not $sub -or $sub.Length -lt 2) { return [IntPtr]::Zero }
    $script:found = [IntPtr]::Zero
    $subLower = $sub.ToLower()
    $cb = [U+EnumWindowsProc]{ param($h, $l)
        if (-not [U]::IsWindowVisible($h)) { return $true }
        $sb = New-Object System.Text.StringBuilder 256
        [U]::GetWindowText($h, $sb, 256) | Out-Null
        if ($sb.ToString().ToLower().Contains($subLower)) { $script:found = $h; return $false }
        return $true
    }
    [U]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    return $script:found
}

# browsers: if already running, open a NEW window instead of just focusing the old one
$IsBrowserName = $Name -match 'chrome|Chrome|谷歌|浏览器|edge|Edge'
$h = [IntPtr]::Zero
if (-not $IsBrowserName) { $h = Find-ExistingWindow $Name }
if ($h -ne [IntPtr]::Zero) {
    Bring-To-Front $h
    Write-Output "OK:$Name (already running, brought to front)"
    exit 0
}

function Start-With-Focus([string]$target, [string]$extra) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($target)
    $preExisting = [bool](Get-Process -Name $base -ErrorAction SilentlyContinue)
    $IsBrowser = $target -match 'chrome|msedge|firefox|360chrome'
    if ($IsBrowser -and $preExisting) {
        # browser already running -> open a fresh window
        if ($extra) { Start-Process $target -ArgumentList "--new-window $extra" } else { Start-Process $target -ArgumentList "--new-window" }
        Write-Output "OK:$target (new window opened)"
        return
    }
    if ($extra) { Start-Process $target -ArgumentList $extra } else { Start-Process $target }
    $budget = if ($preExisting) { 2.5 } else { 5 }
    $deadline = (Get-Date).AddSeconds($budget)
    $h = [IntPtr]::Zero
    while ((Get-Date) -lt $deadline) {
        $p = Get-Process -Name $base -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
        if ($p) { $h = $p.MainWindowHandle; break }
        Start-Sleep -Milliseconds 200
    }
    if ($h -ne [IntPtr]::Zero) {
        Bring-To-Front $h
        Write-Output "OK:$target (window brought to front)"
    } elseif (Get-Process -Name $base -ErrorAction SilentlyContinue) {
        # process alive but no window (single-instance tray handoff): try recall once
        if ($extra) { Start-Process $target -ArgumentList $extra } else { Start-Process $target }
        $deadline2 = (Get-Date).AddSeconds(2)
        while ((Get-Date) -lt $deadline2) {
            $p = Get-Process -Name $base -ErrorAction SilentlyContinue |
                Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
            if ($p) { $h = $p.MainWindowHandle; break }
            Start-Sleep -Milliseconds 200
        }
        if ($h -ne [IntPtr]::Zero) {
            Bring-To-Front $h
            Write-Output "OK:$target (window brought to front)"
        } else {
            # process alive but no window even after recall -> honestly report tray state
            Write-Output "RUNNING:$target (window in tray)"
        }
    } else {
        # no window AND no process -> launch failed to produce anything visible
        Write-Output "FAIL:$target (no window appeared)"
    }
}

$Name = $Name.Trim()
$pat = [regex]::Escape($Name)

# 0) fast path from external UTF-8 sidecar (known apps, incl. CJK names)
$knownFile = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "open_app_known.txt"
if (Test-Path -LiteralPath $knownFile) {
    try {
        foreach ($line in [System.IO.File]::ReadAllLines($knownFile, [System.Text.Encoding]::UTF8)) {
            $line = $line.Trim()
            if (-not $line -or $line.StartsWith("#")) { continue }
            $idx = $line.IndexOf("=")
            if ($idx -lt 0) { continue }
            $key = $line.Substring(0, $idx).Trim()
            $val = $line.Substring($idx + 1).Trim()
            if ($key -eq $Name -and (Test-Path -LiteralPath $val)) {
                # .lnk shortcut -> start the .lnk itself (same as double-click), wait for window
                if ($val -match '\.lnk$') {
                    if ($extra) { Start-Process $val -ArgumentList $extra } else { Start-Process $val }
                    $deadline = (Get-Date).AddSeconds(8)
                    $h = [IntPtr]::Zero
                    while ((Get-Date) -lt $deadline) {
                        $h = Find-ExistingWindow $Name
                        if ($h -ne [IntPtr]::Zero) { break }
                        Start-Sleep -Milliseconds 300
                    }
                    if ($h -ne [IntPtr]::Zero) {
                        Bring-To-Front $h
                        Write-Output "OK:$val (window brought to front)"
                    } else {
                        Write-Output "OK:$val (launched)"
                    }
                    exit 0
                }
                Start-With-Focus $val $Extra
                exit 0
            }
        }
    } catch { }
}

# 1) Registry App Paths
$appPaths = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
)
foreach ($base in $appPaths) {
    Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object {
        $exeName = $_.PSChildName
        if ($exeName -imatch "^$pat.*\.exe$") {
            $path = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).'(default)'
            if ($path -and (Test-Path -LiteralPath $path)) {
                Start-With-Focus $path $Extra
                exit 0
            }
        }
    }
}

# 2) Uninstall registry by DisplayName
$uninstall = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
$app = Get-ItemProperty $uninstall -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -imatch $pat } |
    Select-Object -First 1
if ($app) {
    $cand = @()
    try {
        if ($app.InstallLocation) { $cand += (Join-Path $app.InstallLocation ($Name + ".exe")) }
    } catch { }
    if ($app.DisplayIcon) {
        $icon = ($app.DisplayIcon -split ',')[0].Trim('"')
        if (Test-Path -LiteralPath $icon) { $cand += $icon }
    }
    foreach ($c in $cand) {
        if ($c -and (Test-Path -LiteralPath $c)) {
            Start-With-Focus $c $Extra
            exit 0
        }
    }
    if ($app.InstallLocation -and (Test-Path -LiteralPath $app.InstallLocation)) {
        $exe = Get-ChildItem $app.InstallLocation -Recurse -Filter *.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.BaseName -imatch $pat -and $_.BaseName -inotmatch '^uninstall' } |
            Select-Object -First 1
        if ($exe) {
            Start-With-Focus $exe.FullName $Extra
            exit 0
        }
    }
}

# 3) Start menu shortcuts (launch + verify window; no window -> fall through to next level)
$dirs = @(
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs",
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
)
$lnk = Get-ChildItem $dirs -Recurse -Include *.lnk -ErrorAction SilentlyContinue |
    Where-Object { $_.BaseName -imatch $pat -and $_.BaseName -inotmatch '^uninstall' } |
    Select-Object -First 1
if ($lnk) {
    if ($Extra) { Start-Process $lnk.FullName -ArgumentList $Extra } else { Start-Process $lnk.FullName }
    $deadline = (Get-Date).AddSeconds(8)
    $h = [IntPtr]::Zero
    while ((Get-Date) -lt $deadline) {
        $h = Find-ExistingWindow $Name
        if ($h -ne [IntPtr]::Zero) { break }
        Start-Sleep -Milliseconds 300
    }
    if ($h -ne [IntPtr]::Zero) {
        Bring-To-Front $h
        Write-Output "OK:$($lnk.FullName) (window brought to front)"
        exit 0
    }
    # window not seen -> keep searching (app may still be starting; common-dirs or cmd start will finish)
}

# 4) Common install dirs
$roots = @(
    "$env:ProgramFiles",
    "${env:ProgramFiles(x86)}",
    "$env:LOCALAPPDATA\Programs",
    "$env:USERPROFILE\AppData\Local\Programs",
    "D:\Program Files",
    "D:\Program Files (x86)",
    "D:\Tencent",
    "D:\Software"
)
$exe = Get-ChildItem $roots -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ChildItem $_.FullName -Recurse -Filter *.exe -ErrorAction SilentlyContinue } |
    Where-Object { $_.BaseName -imatch $pat -and $_.BaseName -inotmatch '^uninstall' } |
    Select-Object -First 1
if ($exe) {
    Start-With-Focus $exe.FullName $Extra
    exit 0
}

# 6) cmd start fallback: last resort, then wait for window once more
cmd /c start "" "$Name" 2>$null
$deadline = (Get-Date).AddSeconds(8)
$h = [IntPtr]::Zero
while ((Get-Date) -lt $deadline) {
    $h = Find-ExistingWindow $Name
    if ($h -ne [IntPtr]::Zero) { break }
    Start-Sleep -Milliseconds 300
}
if ($h -ne [IntPtr]::Zero) {
    Bring-To-Front $h
    Write-Output "OK:$Name (window brought to front)"
    exit 0
}

Write-Output "NOTFOUND"
exit 1