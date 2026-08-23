param([string]$TextFile = "", [string]$TitleFile = "")

function Get-TextFromFile([string]$path, [string]$fallback) {
    if ($path -and (Test-Path -LiteralPath $path)) {
        return [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    }
    return $fallback
}

$text = Get-TextFromFile $TextFile "reminder"
$title = Get-TextFromFile $TitleFile ""
if ($title -eq "") { $title = "XiaoNuan" }

# MessageBox 弹窗: 100% 一定显示(Win11 的 Toast 在无包身份进程下经常静默不弹)
$ok = $false
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $icon = [System.Windows.Forms.MessageBoxIcon]::Information
    $buttons = [System.Windows.Forms.MessageBoxButtons]::OK
    [System.Windows.Forms.MessageBox]::Show($text, $title, $buttons, $icon) | Out-Null
    $ok = $true
} catch {
    $ok = $false
}

if ($ok) { Write-Output "OK" } else { Write-Output "FAIL" }