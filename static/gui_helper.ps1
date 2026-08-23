param(
    [string]$Action = "screen",
    [int]$X = -1,
    [int]$Y = -1,
    [string]$TextB64 = "",
    [string]$Keys = "",
    [string]$Dir = "down",
    [string]$Window = "",
    [string]$OutFile = "",
    [int]$Max = 0
)

# pure ASCII file: all text passed as base64 (UTF-8) or ASCII; Chinese handled on Python side
$ErrorActionPreference = "Stop"

try { Add-Type -AssemblyName System.Windows.Forms, System.Drawing } catch {}

Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class GU {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern int GetWindowThreadProcessId(IntPtr h, out int pid);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(int idAttach, int idAttachTo, bool fAttach);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetActiveWindow(IntPtr h);
    [DllImport("kernel32.dll")] public static extern int GetCurrentThreadId();
    public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
}
"@
[GU]::SetProcessDPIAware() | Out-Null

# ---- FAILSAFE: cursor parked at top-left corner (0,0) aborts any physical action ----
function Test-Failsafe {
    $p = [System.Windows.Forms.Cursor]::Position
    if ($p.X -le 1 -and $p.Y -le 1) { Write-Output "ABORT"; exit 1 }
}

function Find-Hwnd([string]$sub) {
    if (-not $sub) { return [IntPtr]::Zero }
    $script:f = [IntPtr]::Zero
    $needle = $sub.ToLower()
    $cb = [GU+EnumWindowsProc]{ param($h, $l)
        if (-not [GU]::IsWindowVisible($h)) { return $true }
        $sb = New-Object System.Text.StringBuilder 256
        [GU]::GetWindowText($h, $sb, 256) | Out-Null
        if ($sb.ToString().ToLower().Contains($needle)) { $script:f = $h; return $false }
        return $true
    }
    [GU]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
    return $script:f
}

function Bring-Front([IntPtr]$h) {
    if ($h -eq [IntPtr]::Zero) { return }
    [GU]::ShowWindow($h, 6) | Out-Null
    [GU]::ShowWindow($h, 5) | Out-Null
    if ($Max -eq 1) { [GU]::ShowWindow($h, 3) | Out-Null } else { [GU]::ShowWindow($h, 9) | Out-Null }
    # AttachThreadInput: 挂接到前台线程取得置前权限, 再 BringWindowToTop + SetForegroundWindow + SetActiveWindow
    $fore = [GU]::GetForegroundWindow()
    $fore_tid = 0
    if ($fore -ne [IntPtr]::Zero) {
        $dummy = 0
        $fore_tid = [GU]::GetWindowThreadProcessId($fore, [ref]$dummy)
    }
    $cur_tid = [GU]::GetCurrentThreadId()
    $attached = $false
    if ($fore_tid -ne 0 -and $fore_tid -ne $cur_tid) {
        $attached = [GU]::AttachThreadInput($cur_tid, $fore_tid, $true)
    }
    [GU]::BringWindowToTop($h) | Out-Null
    [GU]::SetForegroundWindow($h) | Out-Null
    [GU]::SetActiveWindow($h) | Out-Null
    if ($attached) {
        [GU]::AttachThreadInput($cur_tid, $fore_tid, $false) | Out-Null
    }
}

function Get-CursorPos {
    $p = [System.Windows.Forms.Cursor]::Position
    return "$($p.X),$($p.Y)"
}

switch ($Action) {
    "screen" {
        $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        Write-Output "$($b.Width)x$($b.Height)"
    }
    "cursor" {
        Write-Output (Get-CursorPos)
    }
    "mouse" {
        Test-Failsafe
        if ($X -ge 0 -and $Y -ge 0) { [GU]::SetCursorPos($X, $Y) | Out-Null; Start-Sleep -Milliseconds 40 }
        if ($Keys -eq "left_click") { [GU]::mouse_event(2,0,0,0,[UIntPtr]::Zero); [GU]::mouse_event(4,0,0,0,[UIntPtr]::Zero) }
        elseif ($Keys -eq "double_click") { for($i=0;$i -lt 2;$i++){ [GU]::mouse_event(2,0,0,0,[UIntPtr]::Zero); [GU]::mouse_event(4,0,0,0,[UIntPtr]::Zero); Start-Sleep -Milliseconds 50 } }
        elseif ($Keys -eq "right_click") { [GU]::mouse_event(8,0,0,0,[UIntPtr]::Zero); [GU]::mouse_event(16,0,0,0,[UIntPtr]::Zero) }
        Write-Output (Get-CursorPos)
    }
    "scroll" {
        Test-Failsafe
        if ($X -ge 0 -and $Y -ge 0) { [GU]::SetCursorPos($X, $Y) | Out-Null }
        $delta = if ($Dir -eq "up") { 120 } else { -120 }
        [GU]::mouse_event(0x0800, 0, 0, [uint32]$delta, [UIntPtr]::Zero)
        Write-Output "scrolled:$Dir"
    }
    "type" {
        Test-Failsafe
        if (-not $TextB64) { Write-Output "empty"; exit 0 }
        $bytes = [Convert]::FromBase64String($TextB64)
        $txt = [System.Text.Encoding]::UTF8.GetString($bytes)
        [System.Windows.Forms.Clipboard]::SetText($txt, [System.Windows.Forms.TextDataFormat]::UnicodeText)
        Start-Sleep -Milliseconds 80
        [System.Windows.Forms.SendKeys]::SendWait("^v")
        Write-Output "typed"
    }
    "key" {
        Test-Failsafe
        $k = $Keys.Trim().ToLower()
        $map = @{
            "enter"="{ENTER}"; "esc"="{ESC}"; "escape"="{ESC}"; "tab"="{TAB}";
            "backspace"="{BACKSPACE}"; "delete"="{DELETE}"; "del"="{DELETE}";
            "up"="{UP}"; "down"="{DOWN}"; "left"="{LEFT}"; "right"="{RIGHT}";
            "home"="{HOME}"; "end"="{END}"; "pgup"="{PGUP}"; "pgdn"="{PGDN}";
            "space"=" "; "f5"="{F5}"; "f2"="{F2}"
        }
        $parts = $k -split "\+"
        $out = ""
        foreach ($p2 in $parts) {
            if ($p2 -eq "ctrl") { $out += "^" }
            elseif ($p2 -eq "alt") { $out += "%" }
            elseif ($p2 -eq "shift") { $out += "+" }
            else {
                $m = $null
                if ($map.ContainsKey($p2)) { $m = $map[$p2] } else { $m = $p2.ToUpper() }
                $out += $m
            }
        }
        [System.Windows.Forms.SendKeys]::SendWait($out)
        Write-Output "key:$k"
    }
    "front" {
        $h = Find-Hwnd $Window
        if ($h -eq [IntPtr]::Zero) { Write-Output "FRONT:notfound"; exit 0 }
        Bring-Front $h
        $fg = [GU]::GetForegroundWindow()
        Write-Output ("FRONT:ok:" + ($fg -eq $h))
    }
    "frontapp" {
        # front by process name (for apps whose window title changes, e.g. NetEase=cloudmusic).
        # MainWindowHandle may be 0 for elevated processes; fall back to EnumWindows by PID set.
        $procs = @(Get-Process -Name $Window -ErrorAction SilentlyContinue)
        if ($procs.Count -eq 0) { Write-Output "FRONT:noproc"; exit 0 }
        $pids = @($procs | ForEach-Object { $_.Id })
        $h = [IntPtr]::Zero
        foreach ($p in $procs) {
            $mh = $p.MainWindowHandle
            if ($mh -ne [IntPtr]::Zero) { $h = $mh; break }
        }
        if ($h -eq [IntPtr]::Zero) {
            $script:f = [IntPtr]::Zero
            $cb = [GU+EnumWindowsProc]{ param($h2, $l)
                $pid2 = 0
                [GU]::GetWindowThreadProcessId($h2, [ref]$pid2) | Out-Null
                if ($pids -contains $pid2 -and [GU]::IsWindowVisible($h2)) { $script:f = $h2; return $false }
                return $true
            }
            [GU]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
            $h = $script:f
        }
        if ($h -eq [IntPtr]::Zero) { Write-Output "FRONT:nohwnd"; exit 0 }
        Bring-Front $h
        $fg = [GU]::GetForegroundWindow()
        Write-Output ("FRONT:ok:" + ($fg -eq $h))
    }
    "uia" {
        Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
        $hwnd = [IntPtr]::Zero
        if ($Window) { $hwnd = Find-Hwnd $Window } else { $hwnd = [GU]::GetForegroundWindow() }
        $out = @()
        if ($hwnd -ne [IntPtr]::Zero) {
            try {
                $root = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
                $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
                $ids = @(50000,50002,50003,50004,50005,50007,50011,50019,50020,50030)
                $names = @{50000="button";50002="checkbox";50003="combobox";50004="edit";50005="link";50007="listitem";50011="menuitem";50019="tabitem";50020="text";50030="document"}
                $collected = New-Object System.Collections.ArrayList
                $script:depth = 0
                function Walk-Elem([System.Windows.Automation.AutomationElement]$el) {
                    if ($script:depth -gt 12 -or $collected.Count -ge 40) { return }
                    $child = $null
                    try { $child = $walker.GetFirstChild($el) } catch { return }
                    while ($child -ne $null -and $collected.Count -lt 40) {
                        $next = $null
                        try {
                            $ct = $child.Current.ControlType.Id
                            if ($ids -contains $ct) {
                                $nm = ([string]$child.Current.Name).Trim()
                                if ($nm -or $ct -eq 50004 -or $ct -eq 50030) {
                                    $r = $child.Current.BoundingRectangle
                                    $w = [int]($r.Right - $r.Left); $h = [int]($r.Bottom - $r.Top)
                                    if ($w -gt 0 -and $h -gt 0) {
                                        $val = ""
                                        try {
                                            if ($ct -eq 50004 -or $ct -eq 50020 -or $ct -eq 50030) {
                                                $vp = $child.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
                                                $val = [string]$vp.Current.Value
                                            }
                                        } catch { $val = "" }
                                        [void]$collected.Add(@{ name=$nm; type=$names[$ct]; rect=@($([int]$r.Left),$([int]$r.Top),$w,$h); enabled=[bool]$child.Current.IsEnabled; value=$val })
                                    }
                                }
                            }
                            $script:depth++
                            Walk-Elem $child
                            $script:depth--
                            $next = $walker.GetNextSibling($child)
                        } catch { $next = $null }
                        $child = $next
                    }
                }
                Walk-Elem $root
                $out = @($collected | Sort-Object { $_.rect[2] * $_.rect[3] } -Descending | Select-Object -First 40)
            } catch { $out = @() }
        }
        $json = $out | ConvertTo-Json -Compress -Depth 5
        if ($OutFile) {
            [System.IO.File]::WriteAllText($OutFile, $json, (New-Object System.Text.UTF8Encoding($false)))
            Write-Output "uia:written"
        } else {
            [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
            Write-Output $json
        }
    }
    default {
        Write-Output "BADACTION:$Action"
    }
}