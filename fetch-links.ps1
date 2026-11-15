# Save a list of reel links as references (no Instagram login needed), one at a time with a pause.
param([string]$List = "links.txt", [string]$Niche = "real-estate-india")
Set-Location $PSScriptRoot
foreach ($url in Get-Content $List) {
  if (-not $url.Trim()) { continue }
  Write-Output "== $url"
  & .\engine.cmd add-url $url --niche $Niche --skip-analysis
  Start-Sleep -Seconds (Get-Random -Minimum 4 -Maximum 9)
}
