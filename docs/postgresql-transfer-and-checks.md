---
title: PostgreSQL Package Transfer and Repository Checks
description: Download five pinned packages from GAR, verify checksums, upload to JFrog, and check anonymous APT access.
---

## 1. Download and validate

Run in Windows PowerShell with `gcloud` and `jf` already logged in.
The saved JFrog profile `myjfrog` must point to `https://trialha4373.jfrog.io/`.
Use a new download folder. Run the PowerShell blocks in the same session.

```powershell
$ErrorActionPreference = 'Stop'
$folder = Join-Path $env:TEMP ('postgresql-debs-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $folder | Out-Null
$source = @('--project=project-025ac1f2-75d5-497d-a57',
    '--location=australia-southeast1', '--repository=postgres-debs')
$pins = @(
    'postgresql-client-common/versions/293.pgdg13+1'
    'postgresql-common/versions/293.pgdg13+1'
    'libpq5/versions/18.6-1.pgdg13+2'
    'postgresql-client-17/versions/17.11-1.pgdg13+2'
    'postgresql-17/versions/17.11-1.pgdg13+2'
)
$listing = gcloud artifacts files list @source --format=json
if ($LASTEXITCODE -ne 0) { throw 'GAR listing failed' }
$files = @($listing | ConvertFrom-Json | Where-Object {
    $pins -contains ($_.owner -replace '^.*/packages/', '')
})
if ($files.Count -ne 5) { throw 'Expected exactly five package files' }

foreach ($file in $files) {
    $sourceName = [Uri]::UnescapeDataString(($file.name -split '/files/')[1])
    $name = ($sourceName -split '/')[-1] -replace '_[a-f0-9]{32}\.deb$', '.deb'
    gcloud artifacts files download $sourceName @source --destination=$folder --local-filename=$name --quiet
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $name" }
    $path = Join-Path $folder $name
    $expectedHash = ($file.hashes | Where-Object type -eq 'SHA256').value
    if ((Get-FileHash $path -Algorithm SHA256).Hash -ne $expectedHash -or
        (Get-Item $path).Length -ne [long]$file.sizeBytes) {
        throw "Checksum or size mismatch: $name"
    }
    Write-Output "Verified: $name"
}
```

These checks compare downloaded bytes against GAR's SHA-256 and size metadata.
Continue only when all five files print `Verified`.

## 2. Upload and verify JFrog checksums

The destination must be a local Debian repository named `postgresql-debian`.
The `--deb` option tells Artifactory to index packages under `trixie/main`.
Uploads still require authentication, even when downloads are anonymous.

```powershell
foreach ($file in Get-ChildItem $folder -Filter '*.deb') {
    $arch = if ($file.Name.EndsWith('_all.deb')) { 'all' } else { 'amd64' }
    jf rt upload $file.FullName 'postgresql-debian/pool/main/p/' --server-id=myjfrog --flat=true --deb="trixie/main/$arch" --fail-no-op=true
    if ($LASTEXITCODE -ne 0) { throw "Upload failed: $($file.Name)" }

    $name = [Uri]::EscapeDataString($file.Name)
    $response = jf rt curl --server-id=myjfrog -s -f "/api/storage/postgresql-debian/pool/main/p/$name"
    if ($LASTEXITCODE -ne 0) { throw "Remote check failed: $name" }
    $remote = $response | ConvertFrom-Json
    if ($remote.checksums.sha256 -ne (Get-FileHash $file.FullName -Algorithm SHA256).Hash) {
        throw "Remote checksum mismatch: $name"
    }
    Write-Output "Uploaded and verified: $($file.Name)"
}
```

## 3. Enable anonymous downloads

Do this as a JFrog administrator. UI labels vary by version.

1. Open **Administration > Security > Settings** (sometimes **General**).
2. Enable **Allow Anonymous Access** and save. This is an instance-wide switch.
3. Open **Administration > User Management > Permissions**.
4. Create a permission named `postgresql-anonymous-read`.
5. Select only the `postgresql-debian` repository, including all paths (`**`).
6. Add the built-in `anonymous` user and grant only **Read**.
7. Do not grant Deploy/Write, Delete, Annotate, or Manage permissions. Save.
8. Review other anonymous permissions and group memberships so the global switch
   does not expose other repositories unintentionally.

Anyone who can reach the instance can now download these packages. Keep uploads
authenticated and keep GPG signing enabled. Anonymous access does not replace
APT signature validation.

The role also needs the matching ASCII-armored public signing key. Export the
public key for the repository's existing `Debian` key pair and publish it at
`postgresql-debian/public-key.asc`. Do not upload the private key or create a new
key pair. Package uploads do not automatically create this public-key file.

Test without credentials in Linux/WSL. Each command should return HTTP 200,
not a login redirect, 401, 403, or 404:

```bash
repo=https://trialha4373.jfrog.io/artifactory/postgresql-debian
curl -q -fsS -o /dev/null -w '%{http_code}\n' "$repo/dists/trixie/Release"
curl -q -fsS -o /dev/null -w '%{http_code}\n' "$repo/dists/trixie/main/binary-amd64/Packages"
curl -q -fsS -o /dev/null -w '%{http_code}\n' "$repo/public-key.asc"
curl -q -fsS -o /dev/null -w '%{http_code}\n' "$repo/pool/main/p/postgresql-client-common_293.pgdg13+1_all.deb"
```

## 4. Preview the Ansible playbook

Run from this repository's root on your Linux/WSL Ansible controller, with SSH
access to the inventory host. The target must be Debian 13 amd64.
Ansible reports that architecture as `x86_64`, so the existing assertion is correct.

```bash
export JFROG_DEB_REPO_URL=https://trialha4373.jfrog.io/artifactory/postgresql-debian
export JFROG_DEB_SIGNING_KEY_URL="$JFROG_DEB_REPO_URL/public-key.asc"
ansible-playbook playbooks/postgresql.yml --syntax-check
ansible-playbook playbooks/postgresql.yml --check --diff
```

`--syntax-check` checks playbook syntax, not JFrog connectivity.
`--check --diff` previews supported changes without applying them. It is not a
complete first-install test: the key and source file are not created, APT may use
old indexes, and the final PostgreSQL query is skipped. Its following assertion
can fail because no version output exists. A missing service can also fail.
These failures alone do not prove that JFrog is broken.

## 5. Validate APT without installing PostgreSQL

On the Debian target, after the role's signing key and source entry have been
configured, run:

```bash
sudo apt-get update
apt-cache policy postgresql-client-common postgresql-common libpq5 postgresql-client-17 postgresql-17
apt-get --simulate install \
  postgresql-client-common=293.pgdg13+1 \
  postgresql-common=293.pgdg13+1 \
  libpq5=18.6-1.pgdg13+2 \
  postgresql-client-17=17.11-1.pgdg13+2 \
  postgresql-17=17.11-1.pgdg13+2
```

`apt-get update` writes package indexes but installs nothing. It checks repository
metadata and signatures; resolve any repository warnings before continuing.
In `apt-cache policy`, confirm each pinned version lists the JFrog URL.
The simulation checks dependency resolution without installing packages.
Keep normal Debian sources available: these five files are not every dependency.
For a fresh target, configure the public key and source first using the
[repository setup guide](jfrog-debian-repository.md#test-the-repository).