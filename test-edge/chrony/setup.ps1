# Configure this Windows edge host as an NTP client of the PUDA site Chrony server.
# Do not run on the NATS/NTP host — that machine already runs infra/chrony.
#
# Usage (elevated PowerShell):
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NtpServer 100.118.119.115

[CmdletBinding()]
param(
    [string]$NtpServer
)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run in an elevated PowerShell: powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NtpServer <NTP_SERVER>"
}

if (-not $NtpServer) {
    $NtpServer = $env:NTP_SERVER
}

if (-not $NtpServer) {
    throw "Pass -NtpServer <Tailscale/LAN IP of the site Chrony server>."
}

if ($NtpServer -eq 'host.docker.internal') {
    throw "host.docker.internal is a Docker hostname. Use the NTP host Tailscale/LAN IP."
}

Set-Service -Name w32time -StartupType Automatic
Start-Service -Name w32time

& w32tm.exe /config /manualpeerlist:"$NtpServer,0x8" /syncfromflags:manual /reliable:YES /update | Out-Host
Restart-Service -Name w32time
& w32tm.exe /resync /force | Out-Host

Write-Host "Windows Time client pointed at $NtpServer"
& w32tm.exe /query /status | Out-Host
& w32tm.exe /query /peers | Out-Host
