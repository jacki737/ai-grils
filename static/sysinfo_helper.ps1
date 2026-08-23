# sysinfo_helper.ps1 - collect Windows host status, output JSON (ASCII-safe keys)
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs = Get-CimInstance Win32_ComputerSystem

$memTotal = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
$memFree = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
$memUsed = [math]::Round($memTotal - $memFree, 1)

$boot = $os.LastBootUpTime
$upH = 0
if ($boot) { $upH = [math]::Round(((Get-Date) - $boot).TotalHours, 1) }

$diskRows = @()
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
  $total = [math]::Round($_.Size / 1GB, 0)
  $used = [math]::Round(($_.Size - $_.FreeSpace) / 1GB, 0)
  $pct = 0
  if ($total -gt 0) { $pct = [math]::Round($used / $total * 100, 0) }
  $diskRows += ("{0}: {1}G/{2}G ({3}%)" -f $_.DeviceID, $used, $total, $pct)
}

$cpuLoad = $null
$load = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average)
if ($load) { $cpuLoad = [math]::Round($load.Average, 0) }

$battery = $null
$bat = Get-CimInstance Win32_Battery | Select-Object -First 1
if ($bat -and $bat.EstimatedChargeRemaining -ne $null) {
  $battery = "{0}%" -f $bat.EstimatedChargeRemaining
}

$result = [ordered]@{
  os = $os.Caption
  os_build = $os.Version
  machine = $cs.Manufacturer + " " + $cs.Model
  cpu = $cpu.Name
  cpu_load = if ($null -ne $cpuLoad) { "$cpuLoad%" } else { "unknown" }
  mem_used_g = $memUsed
  mem_total_g = $memTotal
  uptime_h = $upH
  disk = ($diskRows -join "; ")
  battery = $battery
  free_ram_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
}
$result | ConvertTo-Json -Compress