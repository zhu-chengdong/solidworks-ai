param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][string]$Receipt,
    [switch]$Restore
)
$ErrorActionPreference='Stop'
$workspaceRoot=[IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$dumpPath=[IO.Path]::GetFullPath($OutputDirectory)
$receiptPath=[IO.Path]::GetFullPath($Receipt)
foreach ($targetPath in @($dumpPath,$receiptPath)) {
    if (-not $targetPath.StartsWith($workspaceRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Diagnostic output must remain in this project.' }
}
$administrator=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $administrator.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Windows requires administrator confirmation for application-specific WER local dumps.' }
$registryPath='HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\SLDWORKS.exe'
$names=@('DumpFolder','DumpCount','DumpType')
if ($Restore) {
    $before=Get-Content -LiteralPath ($receiptPath+'.before.json') -Raw | ConvertFrom-Json
    foreach ($name in $names) {
        $entry=$before.values.PSObject.Properties[$name]
        if ($null -ne $entry) { New-ItemProperty -LiteralPath $registryPath -Name $name -Value $entry.Value.value -PropertyType $entry.Value.kind -Force | Out-Null }
        elseif (Test-Path -LiteralPath $registryPath) { Remove-ItemProperty -LiteralPath $registryPath -Name $name -ErrorAction SilentlyContinue }
    }
    @{status='restored';application='SLDWORKS.exe';date=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath ($receiptPath+'.restore.json') -Encoding utf8
    exit
}
if (Test-Path -LiteralPath $receiptPath) { throw 'Existing diagnostic receipt is preserved.' }
New-Item -ItemType Directory -Path $dumpPath -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $receiptPath) -Force | Out-Null
if ((Get-Item -LiteralPath $dumpPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Dump directory must not be a link.' }
$before=@{existed=(Test-Path -LiteralPath $registryPath);values=@{}}
if ($before.existed) {
    $key=Get-Item -LiteralPath $registryPath
    foreach ($name in $names) {
        if ($key.GetValueNames() -contains $name) { $before.values[$name]=@{value=$key.GetValue($name,$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames);kind=$key.GetValueKind($name).ToString()} }
    }
}
$before | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath ($receiptPath+'.before.json') -Encoding utf8
New-Item -Path $registryPath -Force | Out-Null
New-ItemProperty -LiteralPath $registryPath -Name DumpFolder -PropertyType ExpandString -Value $dumpPath -Force | Out-Null
New-ItemProperty -LiteralPath $registryPath -Name DumpCount -PropertyType DWord -Value 2 -Force | Out-Null
New-ItemProperty -LiteralPath $registryPath -Name DumpType -PropertyType DWord -Value 1 -Force | Out-Null
$after=Get-ItemProperty -LiteralPath $registryPath
if ($after.DumpFolder -ne $dumpPath -or $after.DumpCount -ne 2 -or $after.DumpType -ne 1) { throw 'Application-specific dump configuration readback failed.' }
@{status='enabled';application='SLDWORKS.exe';registry=$registryPath;folder=$dumpPath;dump_type='minidump';maximum_files=2;local_only=$true;captured_crash=$false;date=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding utf8
