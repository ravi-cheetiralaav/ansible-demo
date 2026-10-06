---
title: JFrog CLI Command History
description: JFrog commands executed in this chat for repository diagnostics, five PostgreSQL package uploads, and checksum verification.
---

## Execution context

Commands below were executed in Windows PowerShell, in the order shown.
The upload and verification loops retain their original commands, with formatting expanded for readability.
Existing saved credentials were used; no login, permission-change, or anonymous-access commands were run.

This is a historical record. Running the upload block again uploads the files again.

## 1. Inspect the original default instance

```powershell
jf rt curl -s -f /api/repositories/postgresql-debian
jf c show
jf c show
jf rt curl -I /api/system/ping
```

The configuration was inspected twice. The default profile pointed to
`trialiraviav.jfrog.io`; the ping returned HTTP 302 to its reactivation page.
These commands did not upload anything.

## 2. Check the replacement instance

```powershell
jf rt curl --server-id=myjfrog -i /api/system/ping
jf rt curl --server-id=myjfrog -s -f /api/repositories/postgresql-debian
```

The saved `myjfrog` profile pointed to `trialha4373.jfrog.io`.
The ping returned HTTP 200 with `OK`. Repository inspection confirmed
`postgresql-debian` was a local Debian repository with signing configured.

## 3. Check upload options

```powershell
jf rt upload --help | Select-String -Pattern 'debian|target-props|server-id|flat|fail-no-op' -Context 2,3
```

Confirmed the Debian metadata option: `--deb="distribution/component/architecture"`.

## 4. Upload all five packages

The following loop executed one `jf rt upload` command per file.
All five uploads succeeded. The downloads had already passed source SHA-256 and size checks.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $destination = 'C:\Users\ravi.cheetirala\AppData\Local\Temp\pg-jfrog-trialha4373-20261001'
    $names = @(
        'postgresql-client-common_293.pgdg13+1_all.deb',
        'postgresql-common_293.pgdg13+1_all.deb',
        'libpq5_18.6-1.pgdg13+2_amd64.deb',
        'postgresql-client-17_17.11-1.pgdg13+2_amd64.deb',
        'postgresql-17_17.11-1.pgdg13+2_amd64.deb'
    )
    foreach ($name in $names) {
        $architecture = if ($name.EndsWith('_all.deb')) { 'all' } else { 'amd64' }
        $localPath = Join-Path $destination $name
        jf rt upload $localPath 'postgresql-debian/pool/main/p/' --server-id=myjfrog --flat=true --deb="trixie/main/$architecture" --fail-no-op=true --detailed-summary=true
        if ($LASTEXITCODE -ne 0) { throw "Upload failed: $name" }
    }
}
```

## 5. Verify remote checksums and the APT index

The storage API was queried once per file, followed by one APT index download.
All five remote SHA-256 checksums matched the local files. All five exact package
versions and their SHA-256 values also matched the `trixie/main` amd64 index.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $destination = 'C:\Users\ravi.cheetirala\AppData\Local\Temp\pg-jfrog-trialha4373-20261001'
    $names = @(
        'postgresql-client-common_293.pgdg13+1_all.deb',
        'postgresql-common_293.pgdg13+1_all.deb',
        'libpq5_18.6-1.pgdg13+2_amd64.deb',
        'postgresql-client-17_17.11-1.pgdg13+2_amd64.deb',
        'postgresql-17_17.11-1.pgdg13+2_amd64.deb'
    )
    foreach ($name in $names) {
        $encodedName = [Uri]::EscapeDataString($name)
        $remote = jf rt curl --server-id=myjfrog -s -f "/api/storage/postgresql-debian/pool/main/p/$encodedName" | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw "Remote verification failed: $name" }
        if ($remote.checksums.sha256 -ne (Get-FileHash (Join-Path $destination $name) -Algorithm SHA256).Hash) { throw "Remote checksum mismatch: $name" }
        Write-Output "REMOTE VERIFIED $name"
    }
    $index = (jf rt curl --server-id=myjfrog -s -f '/postgresql-debian/dists/trixie/main/binary-amd64/Packages') -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'Could not retrieve amd64 APT index' }
    foreach ($name in $names) {
        $parts = $name -split '_'
        $package = [regex]::Escape($parts[0])
        $version = [regex]::Escape($parts[1])
        $records = $index -split '\r?\n\s*\r?\n'
        $match = @($records | Where-Object { $_ -match "(?m)^Package: $package\r?$" -and $_ -match "(?m)^Version: $version\r?$" })
        if ($match.Count -ne 1) { throw "Exact package missing or duplicated in amd64 index: $name" }
        $hash = (Get-FileHash (Join-Path $destination $name) -Algorithm SHA256).Hash
        if ($match[0] -notmatch "(?im)^SHA256: $hash\r?$") { throw "APT index checksum mismatch: $name" }
        Write-Output "APT INDEX VERIFIED $($parts[0])=$($parts[1])"
    }
}
```