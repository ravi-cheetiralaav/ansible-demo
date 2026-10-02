---
title: PostgreSQL 17 JFrog and Ansible Runbook
description: Download and publish Debian packages, configure GPG signing and anonymous reads, verify SSH prerequisites, install PostgreSQL, and validate the running server.
ms.date: 2026-10-02
ms.topic: how-to
---

## Lab settings and execution locations

Install the five pinned PostgreSQL packages from JFrog onto a Debian 13 VM.
Ansible runs in WSL Ubuntu and connects over SSH; it is not installed on the VM.
JFrog downloads are anonymous, but package uploads require authentication.
The current role does not configure JFrog credentials or database users.

| Setting | Value |
| --- | --- |
| GCP project | `project-025ac1f2-75d5-497d-a57` |
| GAR source repository | `postgres-debs`, region `australia-southeast1` |
| JFrog instance | <https://trialha4373.jfrog.io> |
| JFrog Debian repository | `postgresql-debian`, distribution `trixie`, component `main` |
| Existing GPG key pair name | `Debian` (case-sensitive) |
| Target VM | `postgres17-lab-2`, zone `australia-southeast1-b` |
| VPC and subnet | `default`, `default` in `australia-southeast1` |
| Last verified public/private IP | `35.189.47.254` / `10.152.0.10` |
| VM SSH user | `ravicheetirala` |
| Target OS | Debian 13 (`trixie`), `amd64` / `x86_64` |

Use Windows PowerShell for package transfer, WSL Bash for GPG and Ansible,
and the VM's shell for post-install checks. Run each section's commands in
the same shell session so its variables remain available.

> [!IMPORTANT]
> The existing lab already has packages and a signing key configured. Do not
> recreate them to rerun Ansible. Start at section 4 for another playbook run.
> Keep `--limit postgres17-lab-2`; the inventory also contains the older VM.

## 1. Download and upload the Debian binaries

### Prepare the tools and destination

Install Google Cloud CLI and JFrog CLI on Windows if absent. You need GAR
read permission, JFrog package deploy/read permission, and an administrator
for repository and signing configuration. In Windows PowerShell:

```powershell
gcloud --version
jf --version
gcloud auth list
```

If not authenticated, run `gcloud auth login`. Always pass the project
explicitly; your default project may be different.

For a new JFrog profile, use the interactive prompt:

```powershell
jf c add myjfrog --url=https://trialha4373.jfrog.io --interactive=true
jf rt ping --server-id=myjfrog
```

Reuse `myjfrog` if already configured. Enter credentials directly into the
CLI's prompt, not into chat, scripts, command-line arguments, or Git.
Anonymous read access does not authorize uploads.

In JFrog Administration, open **Repositories**, create a **Local** repository
with package type **Debian** and key `postgresql-debian`, or reuse it if it
exists. Do not use a Generic repository. Configure its signing key in
section 2. Package upload properties below define `trixie/main` indexing.

### Download from Google Artifact Registry and verify hashes

Run in Windows PowerShell. The fresh folder prevents mixing these artifacts
with earlier downloads. The script verifies each SHA-256 and byte count
against GAR metadata before allowing upload.

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
    if (-not $expectedHash -or
        (Get-FileHash $path -Algorithm SHA256).Hash -ne $expectedHash -or
        (Get-Item $path).Length -ne [long]$file.sizeBytes) {
        throw "Checksum or size mismatch: $name"
    }
    Write-Output "Verified: $name"
}
Write-Output "Download folder: $folder"
```

Continue only after five `Verified` messages. A GAR-generated filename suffix
is removed locally; package contents and versions are not changed. Hash
agreement confirms transfer integrity, not independent publisher provenance;
use an approved source repository.

### Upload with Debian indexing properties

In the same PowerShell session, run:

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

Expect five `Uploaded and verified` messages. The two common packages use
architecture `all`; the other three use `amd64`. The `--deb` flag supplies
distribution/component/architecture properties so Artifactory can generate
APT indexes. Uploading plain files without these properties is insufficient.
Keep Debian's normal mirrors enabled on the VM for additional dependencies.

## 2. Create or reuse the GPG signing key

GPG signing protects APT repository metadata. It is separate from the SSH
key used to log in to the VM. JFrog needs the private signing key; Debian
clients need only the matching public key.

### Existing lab: reuse the Debian key pair

In the `postgresql-debian` repository settings, confirm that **GPG Key Pair**
selects `Debian`. Its public key is available at:

<https://trialha4373.jfrog.io/artifactory/api/security/keypair/Debian/public>

This endpoint was successfully used for installation. You do not need to
upload a separate public-key file into the package repository. Do not create
a new pair or overwrite `Debian` merely because a different key URL is missing.

### New repository only: generate a protected key

Use a trusted Linux signing workstation or WSL with `gpg` installed. Keep
keys outside the workspace and outside Windows-mounted shared folders.

```bash
gpg --version
umask 077
mkdir -p "$HOME/jfrog-signing"
chmod 700 "$HOME/jfrog-signing"
cd "$HOME/jfrog-signing"
export GPG_TTY="$(tty)"
gpg --full-generate-key
```

At the interactive prompts:

1. Select **RSA and RSA**, with a size of **4096 bits**.
2. Set an expiry aligned with your policy, for example `1y`, and plan renewal.
3. Enter an identifiable repository signing name and a real team email.
4. Protect the private key with a strong passphrase entered in the GPG prompt.

Find the full fingerprint, then enter that fingerprint at the next prompt:

```bash
gpg --list-secret-keys --keyid-format LONG --with-fingerprint
read -r -p 'Full fingerprint of the new repository key: ' KEY_FINGERPRINT
gpg --armor --output public-key.asc --export "$KEY_FINGERPRINT"
gpg --armor --output private-key.asc --export-secret-keys "$KEY_FINGERPRINT"
chmod 600 private-key.asc
gpg --show-keys --with-fingerprint public-key.asc
```

The public export begins with `BEGIN PGP PUBLIC KEY BLOCK`. Back up the
private key, passphrase, and revocation certificate in approved protected
storage. Never commit them or put them in a publicly readable repository.

### Import and associate the signing key in JFrog

UI labels vary by JFrog version. As an administrator:

1. Open **Administration > Artifactory > Security > Keys Management**, or
   locate **Key Pairs / Signing Keys** in Administration.
2. Add a GPG key pair with a unique name. For a new instance following this
   lab, use `Debian` only if that name is not already in use.
3. Import the public and private exports into the dedicated key-management
   fields and provide the passphrase through its protected field.
4. Edit `postgresql-debian`, select this pair under **GPG Key Pair**, and save.
5. Trigger the repository's Debian index recalculation if needed after
   configuring signing. Let Artifactory generate the metadata; do not upload
   hand-written indexes alongside its generated indexes.
6. Confirm that `dists/trixie/InRelease`, or both `Release` and `Release.gpg`,
   and the `main/binary-amd64/Packages` index exist.

> [!WARNING]
> Import the private key only into JFrog's protected signing-key management,
> never through the Artifacts upload screen. If your version does not support
> the protected key format or passphrase, consult its signing configuration
> requirements rather than disabling key protection. Remove temporary private
> exports after import and protected backup according to your security policy.

## 3. Enable anonymous read access

Use JFrog's built-in `anonymous` user. Do not create an ordinary account
with that name or assign it a password.

1. As an administrator, review existing `anonymous` permissions and group
   memberships before enabling the instance-wide access switch.
2. Open **Administration > Security > Settings** (sometimes **General**),
   enable **Allow Anonymous Access**, and save.
3. Open **Administration > User Management > Permissions** and create
   `postgresql-anonymous-read`, or edit that permission if it already exists.
4. Select only repository `postgresql-debian` and include all paths with `**`.
5. Add the built-in `anonymous` user and grant only **Read**.
6. Leave Deploy/Write, Delete, Annotate, and Manage permissions unchecked.
7. Save and review effective permissions to ensure other repositories are
   not unintentionally exposed by the global switch.

Anyone who can reach the instance can now download the permitted repository
contents. Keep uploads authenticated and APT signature validation enabled.
The public-key API endpoint must also be anonymously accessible; test it
separately rather than assuming repository permissions cover the API.

Open WSL Ubuntu from Windows PowerShell:

```powershell
wsl -d Ubuntu
```

In WSL Bash, set the actual URLs and test without credentials:

```bash
export JFROG_DEB_REPO_URL=https://trialha4373.jfrog.io/artifactory/postgresql-debian
export JFROG_DEB_SIGNING_KEY_URL=https://trialha4373.jfrog.io/artifactory/api/security/keypair/Debian/public
curl -q -fsS -o /dev/null -w '%{http_code}\n' "$JFROG_DEB_SIGNING_KEY_URL"
curl -q -fsS -o /dev/null -w '%{http_code}\n' "$JFROG_DEB_REPO_URL/dists/trixie/Release"
curl -q -fsS -o /dev/null -w '%{http_code}\n' "$JFROG_DEB_REPO_URL/dists/trixie/main/binary-amd64/Packages"
curl -q -fsS -o /dev/null -w '%{http_code}\n' "$JFROG_DEB_REPO_URL/pool/main/p/postgresql-client-common_293.pgdg13+1_all.deb"
```

Expect HTTP `200` for each. Check the downloaded public-key fingerprint
against the trusted signing administrator's record, not merely against a
second download from the same URL:

```bash
set -o pipefail
curl -q -fsS "$JFROG_DEB_SIGNING_KEY_URL" | gpg --show-keys --with-fingerprint
```

HTTP success alone does not verify metadata signatures. The playbook's APT
refresh, and the manual APT check in section 6, perform signature validation.

## 4. Check playbook prerequisites, SSH, and keys

### Controller and network requirements

Use WSL Ubuntu with Ansible Core 2.16 or newer, `gcloud`, OpenSSH, `curl`, and
GnuPG. In WSL Bash:

```bash
cd /mnt/c/Users/ravi.cheetirala/ansible-demo
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
ansible-playbook --version
gcloud --version
ssh -V
gcloud auth list
```

If WSL's gcloud is not authenticated, run `gcloud auth login` inside WSL.
Windows and WSL have separate CLI state and SSH keys. If tools are missing,
install them using your approved package source before continuing.

Explicit `ANSIBLE_CONFIG` is required because Ansible ignores auto-discovered
configuration in world-writable Windows-mounted directories. Its version
output should name this workspace's config file, not `None`.

The VM needs Python 3, passwordless sudo for the SSH user, and access to
JFrog and Debian mirrors using their configured protocols. Allow SSH only
from the approved controller IP, or use a configured IAP path. The lab's
`allow-ssh-local` rule uses a restricted source `/32`; update that restriction
through an administrator if your public IP changes. Do not open SSH to
`0.0.0.0/0`, disable TLS checks, or expose PostgreSQL port 5432.

### Verify current VM identity and establish WSL SSH

In WSL Bash, query the actual VM before trusting inventory values:

```bash
gcloud compute instances describe postgres17-lab-2 \
  --project=project-025ac1f2-75d5-497d-a57 \
  --zone=australia-southeast1-b \
  --format='yaml(name,id,status,networkInterfaces)'
```

Expect `RUNNING`. Compare the external IP and instance ID with
[inventory/hosts.yml](../inventory/hosts.yml). Ephemeral IPs can change;
recreating a VM also changes its instance ID and host key.

Establish access using WSL's gcloud, then check OS, Python, and sudo:

```bash
gcloud compute ssh ravicheetirala@postgres17-lab-2 \
  --project=project-025ac1f2-75d5-497d-a57 \
  --zone=australia-southeast1-b \
  --command='hostname; cat /etc/os-release; uname -m; python3 --version; sudo -n id -u'
```

Gcloud creates its SSH key if absent and registers the public key using your
GCP access. If prompted for a key passphrase, enter it directly into the
terminal; use `ssh-agent` and `ssh-add` for subsequent Ansible runs. Verify
any first-connection fingerprint through a trusted administrator or GCP
console channel before accepting it. Never bypass a changed-host-key warning.

Expect hostname `postgres17-lab-2`, Debian `13`, `x86_64`, a Python 3 version,
and `0` from the sudo check. Then check local SSH files:

```bash
test -s /home/ravicheetirala/.ssh/google_compute_engine
stat -c '%a %U %n' /home/ravicheetirala/.ssh/google_compute_engine
ssh-keygen -F compute.3658425799697189912 \
  -f /home/ravicheetirala/.ssh/google_compute_known_hosts
```

The private key must belong to your WSL user and have restrictive permissions
such as `600`. If necessary, apply `chmod 600` to that private key. Do not
print its contents. `ssh-keygen -F` should find the verified host entry.

The relevant existing inventory entry is shown below for comparison. Do not
replace the whole inventory or duplicate the host:

```yaml
postgres17-lab-2:
  ansible_host: 35.189.47.254
  ansible_user: ravicheetirala
  ansible_ssh_private_key_file: /home/ravicheetirala/.ssh/google_compute_engine
  ansible_ssh_common_args: >-
    -o HostKeyAlias=compute.3658425799697189912
    -o UserKnownHostsFile=/home/ravicheetirala/.ssh/google_compute_known_hosts
    -o StrictHostKeyChecking=yes
```

### Validate Ansible connectivity and privilege escalation

From the workspace root in WSL:

```bash
ansible-playbook playbooks/postgresql.yml --syntax-check
ansible-playbook playbooks/postgresql.yml --limit postgres17-lab-2 --list-hosts
ansible postgres17-lab-2 -m ansible.builtin.ping
ansible postgres17-lab-2 --become -m ansible.builtin.command -a 'id -u'
```

Expect syntax success, exactly one selected host (`postgres17-lab-2`), `pong`,
and `0` from the become test. Ansible ping tests SSH and remote Python, not
ICMP. Stop and resolve failures before installation. The command-module
privilege test may report `CHANGED`; it only runs the read-only `id` command.

## 5. Run the playbook

In WSL Bash, set these values in every new controller session:

```bash
cd /mnt/c/Users/ravi.cheetirala/ansible-demo
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
export JFROG_DEB_REPO_URL=https://trialha4373.jfrog.io/artifactory/postgresql-debian
export JFROG_DEB_SIGNING_KEY_URL=https://trialha4373.jfrog.io/artifactory/api/security/keypair/Debian/public
ansible-playbook playbooks/postgresql.yml --limit postgres17-lab-2
```

No JFrog username or access token is required for this anonymous-download
role. The repository URL must be its root; the key URL must use HTTPS and
the same host. No `.asc` suffix is required on the URL itself.

The [playbook](../playbooks/postgresql.yml) invokes the
[PostgreSQL role](../roles/postgresql/tasks/main.yml) with sudo. It checks
Debian 13 amd64, removes the old GAR source/key paths, downloads the public
key, writes a `signed-by` APT source, installs the
[pinned versions](../roles/postgresql/defaults/main.yml), starts PostgreSQL,
and asserts that a local SQL connection reports server major version 17.

On 2026-10-02, the lab installation completed with:

```text
postgres17-lab-2 : ok=11 changed=3 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
```

Future runs must show `failed=0` and `unreachable=0`; changed counts depend on
the starting state. Run the same command again to check idempotency. Expect
`changed=0` if nothing has drifted; that second-run result is not recorded here.

> [!NOTE]
> `--check --diff` is not a reliable fresh-install gate for this role. It
> does not create the key/source or install packages, and the final SQL
> command is skipped in check mode. Service or version assertions may fail
> even when a normal installation would succeed.

## 6. Verify the installation manually

### Connect to the target

From WSL Bash:

```bash
gcloud compute ssh ravicheetirala@postgres17-lab-2 \
  --project=project-025ac1f2-75d5-497d-a57 \
  --zone=australia-southeast1-b
```

Run the remaining checks in the **Debian VM shell**, not on the controller.
They do not create databases, users, or application data. The APT refresh
updates package indexes but does not upgrade or install packages.

### Check installed versions and repository configuration

```bash
dpkg-query -W -f='${Package}\t${Version}\t${Status}\n' \
  postgresql-client-common postgresql-common libpq5 postgresql-client-17 postgresql-17
cat /etc/apt/sources.list.d/postgresql-jfrog.list
ls -l /usr/share/keyrings/postgresql-jfrog.asc
sudo apt-get update
apt-cache policy postgresql-client-common postgresql-common libpq5 postgresql-client-17 postgresql-17
```

Each package should show `install ok installed` with these versions:

| Package | Expected version |
| --- | --- |
| `postgresql-client-common` | `293.pgdg13+1` |
| `postgresql-common` | `293.pgdg13+1` |
| `libpq5` | `18.6-1.pgdg13+2` |
| `postgresql-client-17` | `17.11-1.pgdg13+2` |
| `postgresql-17` | `17.11-1.pgdg13+2` |

The APT source must use `signed-by=/usr/share/keyrings/postgresql-jfrog.asc`,
the JFrog repository, and `trixie main`. The public key should be root-owned
with mode `0644`. The APT refresh must report no signature or repository
errors; do not accept warnings about stale indexes as success. In
`apt-cache policy`, verify the pinned versions are available from the JFrog
URL. Policy shows current availability, not historical download provenance.

### Check the cluster and actual database server

```bash
pg_lsclusters
systemctl is-enabled postgresql
systemctl is-active postgresql@17-main
pg_isready -h /var/run/postgresql -p 5432
sudo -u postgres psql -X -h /var/run/postgresql -p 5432 -d postgres -v ON_ERROR_STOP=1 -c 'SELECT version();'
sudo -u postgres psql -XAt -h /var/run/postgresql -p 5432 -d postgres -v ON_ERROR_STOP=1 -c 'SHOW server_version_num;'
sudo -u postgres psql -XAt -h /var/run/postgresql -p 5432 -d postgres -v ON_ERROR_STOP=1 -c 'SELECT 1;'
```

For this fresh lab, expect `17/main` online on port `5432`, boot enablement
`enabled`, cluster service `active`, readiness `accepting connections`, server
version `17.11`, numeric version `170011`, and SQL result `1`. If the cluster
name or port differs, investigate `pg_lsclusters` and adjust the checks to
the intended PostgreSQL 17 cluster instead of testing another instance.

The umbrella `postgresql` service can show `active (exited)`; the cluster
unit and successful SQL query prove the server is running. `psql --version`
alone only verifies the client binary.

### Check listening addresses and diagnose failures

```bash
sudo -u postgres psql -XAt -h /var/run/postgresql -p 5432 -d postgres -c 'SHOW listen_addresses;'
sudo ss -ltnp 'sport = :5432'
sudo journalctl -u postgresql@17-main -n 50 --no-pager
sudo tail -n 50 /var/log/postgresql/postgresql-17-main.log
```

Expect local-only TCP listeners (`127.0.0.1` and/or `::1`) with
`listen_addresses` set to `localhost`. The playbook leaves package defaults
in place; it does not harden a previously modified database configuration.
Investigate any wildcard listener before considering the host ready. Review
logs for startup, authentication, or disk errors; avoid sharing sensitive
log contents publicly. Use `exit` to return to WSL after verification.

## 7. Run from a GitLab pipeline

The repository includes [.gitlab-ci.yml](../.gitlab-ci.yml) and a separate
[CI inventory](../inventory/ci.yml). Your WSL inventory remains unchanged.
The pipeline installs PostgreSQL from the existing JFrog repository; it does
not provision a VM, upload packages, create signing keys, or change permissions.

The workflow is:

1. Create a pipeline on the protected default branch.
2. Run `validate` automatically to check playbook syntax and selected hosts.
3. Select the manual `deploy_postgresql` job when ready to change the VM.
4. Check anonymous JFrog access, SSH/Python connectivity, and sudo, then run
  the playbook against only `postgres17-lab-2`.
5. Read the job recap and server-version assertion. Use section 6 for
  independent manual verification.

The pipeline is intentionally skipped on other branches and merge requests.
Deployment is a blocking manual job, and `resource_group` prevents concurrent
deployment jobs for this VM within this GitLab project. No SSH keys or
known-host files are published as job artifacts or cached.

### Runner tools and plugins

Use a self-managed Linux runner with the **Docker executor** and tag
`ansible-gcp`. A small runner with roughly 2 vCPUs and 2 GB RAM is a reasonable
starting point for this one-host lab; adjust for concurrent jobs.

| Location | Requirement | Purpose |
| --- | --- | --- |
| Runner host | Registered GitLab Runner and a supported Docker Engine | Poll GitLab and start isolated job containers. |
| Runner registration | Tag `ansible-gcp`, access to this project, protected runner | Match the pipeline jobs and restrict privileged deployment access. |
| Job image | `python:3.12-slim-bookworm` | Supply Linux, a POSIX shell, Python 3.12, pip, and APT. |
| Installed by the job | OpenSSH client, CA certificates, curl | SSH with host verification and HTTPS prechecks. |
| Installed by the job | `ansible-core>=2.19,<2.20` | Run the existing playbook and built-in modules. |
| Target Debian VM | Python 3, SSH server, sudo, APT, systemd | Execute Ansible modules and install/manage PostgreSQL. |

No Ansible plugin, GitLab plugin, Galaxy collection, JFrog CLI, Google Cloud
CLI, Docker-in-Docker, or privileged container is needed in the job. All
playbook modules are `ansible.builtin`. GitLab's runner/helper handles the
repository checkout. The runner does not need a GCP service-account JSON key
for this direct SSH workflow.

Register the runner using GitLab's **Settings > CI/CD > Runners** setup flow;
enter its authentication token directly on the runner host. Mark it protected,
restrict it to this project, disable untagged jobs, and do not mount the
Docker socket or sensitive host directories inside the job container. A
Shell executor ignores `image:` and is not supported by this pipeline as-is.

The sample resolves the latest available Ansible 2.19 patch during each run.
For production, build an approved job image with tested package versions,
pin its image digest, and remove the runtime APT/pip installation commands.
Maintain that image for security fixes instead of freezing it indefinitely.

### Required connectivity

| Source | Destination | Port/protocol and reason |
| --- | --- | --- |
| Runner host and checkout helper | Your GitLab instance | Outbound HTTPS 443 for polling, jobs, and HTTPS repository checkout. |
| Runner host | Docker Hub registry, authentication, and image CDN endpoints, or an approved mirror | Outbound HTTPS 443 to pull the Python and GitLab helper images. |
| Job container | Debian package mirrors | Outbound HTTP 80 or HTTPS 443 as configured by the image, for APT bootstrap. |
| Job container | `pypi.org` and `files.pythonhosted.org`, or an approved Python mirror | Outbound HTTPS 443 to install Ansible and dependencies. |
| Job container | `trialha4373.jfrog.io` | Outbound HTTPS 443 for repository and public-key prechecks. |
| Job container | Target VM address | TCP 22 for SSH, Ansible module transfer, and local SQL verification. |
| Target VM | `trialha4373.jfrog.io` | Outbound HTTPS 443 for the key, signed metadata, and `.deb` downloads. |
| Target VM | Its configured Debian mirrors | HTTP 80 or HTTPS 443 for dependencies not included in the five uploads. |
| Runner host, job container, and VM | Approved DNS resolvers | DNS resolution, typically UDP/TCP 53, and working TLS trust. |

You do not need inbound connections from GitLab to the runner, or any runner
connection to PostgreSQL port 5432. SQL validation runs locally through SSH.
Install your organization's CA chain when a proxy performs TLS inspection;
do not bypass certificate verification. Include required proxy/mirror settings
in the runner and image when direct internet access is unavailable.

Prefer placing the runner in the same GCP VPC, or a connected network, and
using the VM's verified private address (`10.152.0.10` at last check). Allow
TCP 22 from the runner's actual source address/range to the target VM using
a narrowly scoped firewall rule. Same-VPC placement does not itself authorize
SSH. Docker bridge traffic normally leaves through the runner host; verify
the effective source address before setting the firewall rule.

For public-address access, use a stable runner egress IP and allow only that
IP's `/32`. The existing workstation SSH rule does not automatically allow
the runner. Shared hosted runners may have changing egress IPs and no route
to private GCP addresses. This pipeline has no IAP tunnel; IAP-only access
requires a separate authenticated proxy/tunnel design.

### Prepare a dedicated SSH identity and trusted host key

Use a dedicated deployment identity instead of uploading your personal WSL
private key. On a trusted administration workstation, generate a separate
key if your policy allows long-lived CI SSH keys:

```bash
ssh-keygen -t ed25519 -f "$HOME/.ssh/gitlab_postgresql_deploy" -C gitlab-postgresql-lab
```

This sample has no interactive passphrase or SSH-agent setup. It requires a
key usable noninteractively, such as a dedicated key without a passphrase
stored in GitLab's protected File variable. If your policy forbids that,
integrate an approved secret manager, agent, or short-lived SSH certificate
workflow before using this pipeline. Do not strip your personal key's passphrase.

Have the GCP/VM administrator authorize the new **public** key for the intended
Linux user and verify that `sudo -n` works. With metadata-based SSH, use the
approved instance metadata or account authorization mechanism. With OS Login
enabled, use the approved OS Login identity, public-key registration, and IAM
roles instead; metadata SSH keys are ignored. Use the actual assigned Linux
username in CI. The sample does not refresh OS Login keys or support interactive
SSH MFA. Do not disable OS Login or MFA to make it work.

The playbook requires root-level package and service management, so access
to this CI credential is effectively administrative access to the target VM.
Review deployment code and restrict who can modify protected variables and
run deployment jobs.

The host key is a separate public key identifying the VM. From the already
trusted WSL session, display the verified entry:

```bash
ssh-keygen -F compute.3658425799697189912 \
  -f /home/ravicheetirala/.ssh/google_compute_known_hosts
```

Use the matching known-host entry in GitLab, including its hostname/alias,
algorithm, and public key. Confirm the fingerprint with an administrator
before first use. Do not run an unverified `ssh-keyscan` inside CI and trust
whatever responds. If the VM is recreated, verify and update both the alias
and known-host entry before deployment.

### Configure GitLab CI variables

In **Settings > CI/CD > Variables**, add the following protected variables.
Use the default environment scope `*` or `postgresql-lab` for deployment-only
values. File variables provide a temporary file path to the job, not the
file's contents as an environment string.

| Variable | Type | Value |
| --- | --- | --- |
| `POSTGRES_HOST` | Variable | A currently verified address reachable from the runner: private `10.152.0.10`, or public `35.189.47.254` with restricted SSH ingress. |
| `POSTGRES_SSH_USER` | Variable | The user authorized for the CI public key; `ravicheetirala` only if you authorized that account. |
| `POSTGRES_HOST_KEY_ALIAS` | Variable | `compute.3658425799697189912` for the current VM, matching the trusted host-key entry. |
| `SSH_PRIVATE_KEY` | File | Complete dedicated private key, including BEGIN/END lines and a final newline. |
| `SSH_KNOWN_HOSTS` | File | Verified known-host entry matching the alias, with a final newline. |

Disable variable expansion for key contents. Multiline SSH keys may not meet
GitLab's masking requirements; do not rely on masking to protect them.
Never echo, print, or archive these files, and do not enable `CI_DEBUG_TRACE`.
Protected variables are still accessible to trusted job code, so restrict
protected-branch changes and runner administration. Do not put secrets in
manual-job variable overrides or committed YAML.

The two public JFrog URL variables are already in the pipeline. Override them
in project variables only when moving to another approved repository. No
JFrog token or GPG private signing key belongs in this deployment pipeline.

### Run and interpret the pipeline

1. Publish the pipeline, CI inventory, and existing playbook/role files to
  your GitLab project through your normal review process.
2. Confirm the default branch is protected and the tagged runner is online.
3. Use **Build > Pipeline editor > Validate** to check the configuration
  against your GitLab version before running it.
4. Use **Build > Pipelines > New pipeline** on the protected default branch.
5. Wait for `validate` to pass, then select **Play** for `deploy_postgresql`.
6. Expect `pong`, sudo output `0`, and a playbook recap with `failed=0` and
  `unreachable=0`. A subsequent deployment should be unchanged if no drift
  has occurred.

Restrict deployment access to the `postgresql-lab` environment where your
GitLab edition supports protected environments and approvals. A manual job
alone is a pause, not a complete authorization policy. Review job failures
before retrying; Ansible does not automatically roll back a partial install.

If jobs are pending, check runner tags and protected-runner eligibility. If
no pipeline is created, check the protected default-branch workflow rule.
For SSH errors, verify the source firewall rule, File variable type, key
newline, username, permissions, and matching host alias. If the runtime has
no internet egress, use the approved prebuilt image and mirrors described above.

## 8. Uninstall PostgreSQL 17 without deleting databases

Use [playbooks/postgresql-uninstall.yml](../playbooks/postgresql-uninstall.yml)
from the WSL controller. Its host pattern is fixed to `postgres17-lab-2`;
the original `postgres17-lab` VM is not targeted. The VM itself is not deleted.

> [!WARNING]
> Uninstalling stops PostgreSQL 17 and interrupts applications using it.
> Before doing this on a system with important data, arrange downtime and
> take a verified database backup. Retaining files is not a backup or a
> tested recovery procedure. This playbook does not create a backup.

The playbook uses `ansible.builtin.apt` with `state: absent`, `purge: false`,
and `autoremove: false`. Debian's package removal scripts stop the server.
It then verifies package absence, checks that PostgreSQL 17 clusters are
stopped when the common tools are installed, and checks that the standard
data/configuration directories present before removal still exist.

| Removed | Retained |
| --- | --- |
| `postgresql-17` server package | Database files under `/var/lib/postgresql/17/main` |
| `postgresql-client-17` version-specific client package | Cluster configuration under `/etc/postgresql/17/main` |
| PostgreSQL 17 server/client binaries | `postgresql-common`, `postgresql-client-common`, `libpq5`, and other dependencies |
| Running PostgreSQL 17 service | PostgreSQL OS account, logs, JFrog APT source, and signing key |

Do not use `pg_dropcluster`, enable purge/autoremove, or delete database
directories as part of this procedure. Full data destruction requires a
separate, explicitly approved operation. Other PostgreSQL major versions
are not requested for removal; review APT's plan for dependent packages
before every uninstall.

### Preview and execute the uninstall

Use the SSH key, known-host entry, inventory address, and sudo prerequisites
from section 4. No JFrog environment variables or token are needed by the
uninstall playbook.

In WSL Bash:

```bash
cd /mnt/c/Users/ravi.cheetirala/ansible-demo
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
export ANSIBLE_INVENTORY="$PWD/inventory/hosts.yml"
ansible-playbook playbooks/postgresql-uninstall.yml --syntax-check
ansible-playbook playbooks/postgresql-uninstall.yml --limit postgres17-lab-2 --list-hosts
ansible-playbook playbooks/postgresql-uninstall.yml --limit postgres17-lab-2 --check --diff
```

Confirm that only `postgres17-lab-2` is selected and that APT lists only
`postgresql-17` and `postgresql-client-17` for removal. Stop and investigate
if additional packages would be removed. Check mode does not uninstall;
post-removal assertions are deliberately skipped because packages still exist.

After reviewing the preview, execute:

```bash
ansible-playbook playbooks/postgresql-uninstall.yml --limit postgres17-lab-2
```

Running the same command again should report `changed=0` if the machine
has not changed. The existing GitLab pipeline remains installation-only;
running its manual deployment job will reinstall PostgreSQL, not uninstall it.

### Verify the uninstalled state

On the target VM, run:

```bash
dpkg-query -W -f='${Package}\t${Status}\n' postgresql-17 postgresql-client-17
dpkg-query -W -f='${Package}\t${Status}\n' postgresql-common postgresql-client-common libpq5
sudo pg_lsclusters --json
sudo ls -ld /var/lib/postgresql/17/main /etc/postgresql/17/main
sudo cat /var/lib/postgresql/17/main/PG_VERSION
```

For removed packages, `dpkg-query` may report `deinstall ok config-files`
or a missing-package error; neither means the package remains installed.
The shared packages should still show `install ok installed`.
The retained `17/main` cluster should report `running: 0` and
`binaries_missing: 1`, and `PG_VERSION` should contain `17`.
The umbrella `postgresql` systemd service can still exist because
`postgresql-common` is retained; its presence does not mean a server is running.
Do not use `psql` or `pg_isready` as uninstall checks: their version-specific
binaries have been removed.

On 2026-10-02, the uninstall was executed against `postgres17-lab-2`
at `35.189.47.254`:

```text
Initial removal: ok=8  changed=1 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
Repeat with cluster assertion: ok=10 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
```

Both PostgreSQL 17 packages were confirmed absent. Independent checks found
`17/main` stopped with missing binaries, and confirmed that the data directory,
its `PG_VERSION` file, and the configuration directory remained. These checks
confirm retained paths, not full database integrity or restore readiness.

### Reinstall later

To restore server binaries, follow section 5 using the existing pinned
PostgreSQL 17 packages, then repeat the SQL and service checks in section 6.
The same-major installation can use the retained cluster; do not initialize
or overwrite it. Verify package availability and take a backup of retained
data before recovery work. Reinstallation and database recovery were not
executed as part of this uninstall. PostgreSQL remains uninstalled on the VM.

## Troubleshooting reference

| Symptom | Check or action |
| --- | --- |
| JFrog `401` or `403` | Check the global anonymous switch and effective Read permission; test the key API separately. |
| JFrog `404` for the key | Use the verified `/api/security/keypair/Debian/public` URL, not the absent `/postgresql-debian/public-key.asc` artifact. |
| Redirect or HTML instead of a key | Use the Artifactory API URL, not the browser UI URL; do not treat HTTP success alone as a valid key. |
| `NO_PUBKEY` or invalid signature | Compare the trusted fingerprint with the downloaded key and JFrog repository signing configuration; regenerate signed indexes if needed. Never use `trusted=yes` or allow unauthenticated APT packages. |
| Pinned version unavailable | Check all five uploads, Debian properties, architecture, and index recalculation. Do not silently change versions. |
| SSH timeout or public-key failure | Check VM state/IP, source-IP firewall restriction, WSL gcloud identity, private-key path, and user. |
| SSH host-key mismatch | Verify the instance identity and new fingerprint through a trusted channel before updating known hosts. Keep strict checking enabled. |
| Ansible config reports `None` | Set `ANSIBLE_CONFIG` explicitly from the workspace root in WSL. |
| SQL connection or cluster failure | Inspect `pg_lsclusters`, the cluster service, PostgreSQL logs, and free disk space. Do not delete or recreate data directories as a shortcut. |
