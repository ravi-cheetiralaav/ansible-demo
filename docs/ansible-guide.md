---
title: PostgreSQL Ansible workspace guide
description: Workspace layout, prerequisites, playbook walkthrough, and execution steps for the PostgreSQL 17 lab.
---

## What Ansible does here

Ansible runs on your WSL Ubuntu machine (the control node). It connects to the
Debian 13 VM over SSH (the managed node) and applies a series of tasks. You do
not need to install Ansible on the VM. Each task describes the desired state:
for example, a package should be present or a service should be running.
Running the playbook again should leave an already configured VM unchanged.

This lab installs PostgreSQL 17.11 from a private JFrog Artifactory Debian
APT repository. It keeps PostgreSQL's default local-only access; it does
not create database users or open port 5432 in the GCP firewall.

## Workspace layout

```text
ansible-demo/
|-- README.md
|-- ansible.cfg
|-- inventory/
|   `-- hosts.yml
|-- playbooks/
|   `-- postgresql.yml
|-- roles/
|   `-- postgresql/
|       |-- defaults/
|       |   `-- main.yml
|       `-- tasks/
|           `-- main.yml
`-- docs/
    `-- ansible-guide.md
```

* [ansible.cfg](../ansible.cfg) points Ansible at the inventory and roles, and
  requires SSH host-key verification.
* [inventory/hosts.yml](../inventory/hosts.yml) identifies the `postgres` host
  group, VM address, SSH user, WSL private key, and known-host settings. An
  inventory is the list of machines Ansible can manage.
* [playbooks/postgresql.yml](../playbooks/postgresql.yml) is the entry point.
  Its `hosts: postgres` selects that inventory group, `become: true` runs
  privileged tasks through sudo, and `roles: postgresql` loads the role.
* [roles/postgresql/defaults/main.yml](../roles/postgresql/defaults/main.yml)
  reads JFrog settings from the controller environment and pins exact package
  versions. These are role variables used by the tasks.
* [roles/postgresql/tasks/main.yml](../roles/postgresql/tasks/main.yml) contains
  the installation and post-install validation tasks in execution order.
* [README.md](../README.md) is the short project overview.

## Prerequisites

* Use WSL Ubuntu with Ansible Core 2.16 or newer, `gcloud`, and an SSH client.
  Run the commands below inside WSL, not in the Windows PowerShell shell.
* The existing `postgres17-lab` VM must be running in
  `australia-southeast1-b` on Debian 13 amd64, with Python 3 and passwordless
  sudo available to the SSH user.
* Create a JFrog local Debian repository (for example, `postgres-debs`) with
  distribution `trixie` and component `main`. Enable GPG signing for its
  Release metadata and make its ASCII-armored public signing key available at
  an HTTPS URL. Upload the five pinned packages as described below. Grant a
  read-only JFrog identity access to the repository and key URL.
* The VM needs outbound HTTPS access to JFrog and Debian package mirrors and
  must trust the TLS certificate used by JFrog. Do not disable certificate or
  APT signature validation.
* SSH to the VM must be allowed from your current public IP. The temporary
  `allow-ssh-local` firewall rule was restricted to a single source `/32`;
  if your IP changes, update that restricted rule before connecting. Do not
  broaden it to the entire internet.
* Compare the VM's current external IP and SSH identity with
  [inventory/hosts.yml](../inventory/hosts.yml). Its current address is
  `34.40.252.185`. If the VM is recreated, the host-key alias and known-host
  entry may also change. Do not turn off host-key checking to work around a
  mismatch; verify the new VM identity first.
* The JFrog repository must index the pinned packages listed in the role
  defaults. Standard Debian repositories provide other dependencies. A JFrog
  access token is required; the playbook stores it in root-only APT auth
  configuration on the VM, not in the APT source file.

## Upload the Debian packages to JFrog

Obtain the exact `.deb` files below from a trusted Debian 13 amd64 staging
machine with the PostgreSQL PGDG APT source configured, or from your existing
verified package artifacts. Check their provenance and hashes before upload;
do not rename packages or substitute newer versions. On the staging machine:

```bash
mkdir -p postgres-debs
cd postgres-debs
apt download \
  'postgresql-client-common=293.pgdg13+1' \
  'postgresql-common=293.pgdg13+1' \
  'libpq5=18.6-1.pgdg13+2' \
  'postgresql-client-17=17.11-1.pgdg13+2' \
  'postgresql-17=17.11-1.pgdg13+2'
for package in ./*.deb; do
  dpkg-deb -f "$package" Package Version Architecture
  sha256sum "$package"
done
```

Create a local **Debian** repository in Artifactory, not a generic file
repository or RPM/YUM repository. Configure Debian indexing for `trixie/main`
and GPG-sign its Release metadata. Upload each `.deb` to its `pool/` path with
the correct Debian matrix properties; `all` packages must use architecture
`all`, while machine-specific packages use `amd64`. From a trusted upload
host with the packages in the current directory:

```bash
export JFROG_DEB_REPO_URL='https://artifactory.example.com/artifactory/postgres-debs'
export JFROG_USER='your-jfrog-service-user'
read -r -s -p 'JFrog access token: ' JFROG_ACCESS_TOKEN
echo
export JFROG_ACCESS_TOKEN
umask 077
auth_file="$(mktemp)"
trap 'rm -f "$auth_file"' EXIT
jfrog_host="${JFROG_DEB_REPO_URL#https://}"
jfrog_host="${jfrog_host%%/*}"
printf 'machine %s login %s password %s\n' \
  "$jfrog_host" "$JFROG_USER" "$JFROG_ACCESS_TOKEN" > "$auth_file"
for package in ./*.deb; do
  architecture="$(dpkg-deb -f "$package" Architecture)"
  curl --fail-with-body --show-error --netrc-file "$auth_file" \
    --upload-file "$package" \
    "$JFROG_DEB_REPO_URL/pool/$(basename "$package");deb.distribution=trixie;deb.component=main;deb.architecture=$architecture"
done
```

Use an identity with deploy permission for upload. Trigger or wait for the
Artifactory Debian metadata/index calculation and verify that the signed
`dists/trixie/InRelease` (or `Release` and `Release.gpg`) and `Packages` index
are present. Publish the matching ASCII-armored **public** signing key at a
HTTPS URL reachable by the VM; keep the private signing key in JFrog. The
playbook requires the public key URL separately. Do not commit tokens, the
temporary auth file, or private signing keys.

## Configure JFrog access for Ansible

On the WSL control node, set these environment variables before running the
playbook. Use a read-only user/token for installation, not the upload token.
The signing key URL must return an ASCII-armored public key (`.asc`) over
HTTPS on the same host as the Debian repository. The playbook sends the JFrog
credentials when downloading it.

```bash
export JFROG_DEB_REPO_URL='https://artifactory.example.com/artifactory/postgres-debs'
export JFROG_DEB_SIGNING_KEY_URL='https://artifactory.example.com/path/to/postgresql-public.asc'
export JFROG_USER='your-jfrog-read-only-user'
read -r -s -p 'JFrog read-only access token: ' JFROG_ACCESS_TOKEN
echo
export JFROG_ACCESS_TOKEN
```

The URL must be the repository root, not a package file or a `dists/` path.
Ansible writes credentials to `/etc/apt/auth.conf.d/postgresql-jfrog.conf`
with mode `0600`; the APT source contains no credentials. Store tokens in a
secret manager for automated runs and rotate them according to your policy.

## Prepare WSL access

From Windows PowerShell, open WSL:

```powershell
wsl -d Ubuntu
```

Then enter the workspace inside WSL:

```bash
cd /mnt/c/Users/ravi.cheetirala/ansible-demo
ansible --version
```

Use `gcloud` from **inside WSL** once to establish that environment's SSH key
and trusted host entry. The earlier Windows SSH session used a separate key.
Exit the SSH session after confirming you reached `postgres17-lab`:

```bash
gcloud compute ssh postgres17-lab \
  --project=project-025ac1f2-75d5-497d-a57 \
  --zone=australia-southeast1-b
```

This project lives on a Windows-mounted filesystem. WSL may report the folder
as world-writable, which makes Ansible ignore automatically discovered
configuration. Set the config path explicitly in each new WSL shell:

```bash
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
```

## Check before installing

These commands do not install PostgreSQL. The first checks YAML and role
resolution locally; the second shows the selected VM; the third tests SSH and
remote Python without changing the VM:

```bash
ansible-playbook playbooks/postgresql.yml --syntax-check
ansible-inventory --graph
ansible postgres -m ansible.builtin.ping
```

Ansible's `ping` is a module test, not an ICMP network ping. It should return
`pong` for `postgres17-lab`. If it cannot connect, check the inventory IP,
source-IP firewall rule, WSL SSH key, and trusted host entry before running
the installer.

## What each task does

The playbook gathers OS facts first, then runs the role tasks in order:

1. `Require Debian 13 amd64` stops before package changes if the VM has the
   wrong operating system or CPU architecture. The uploaded packages target
   Debian 13 amd64.
2. `Require JFrog repository settings` checks that the HTTPS repository URL,
  signing-key URL, username, and token were supplied on the control node.
3. `Remove old Artifact Registry APT source` and signing key remove the
  previous GAR configuration so APT no longer contacts GAR.
4. `Configure JFrog APT credentials` creates a root-only APT auth file. The
  signing-key task downloads the public key over HTTPS using JFrog credentials.
5. `Configure PostgreSQL JFrog repository` creates the APT source for
  `trixie main`, using `signed-by` to scope trust to the JFrog public key.
6. `Install PostgreSQL 17 packages` refreshes the package index after adding
   the repository, then installs the five exact versions in role defaults:
   server, client, common packages, and `libpq5`. APT resolves additional
  dependencies from Debian.
7. `Enable and start PostgreSQL` makes the PostgreSQL service start now and
   after reboot. A running service by itself does not prove the database
   accepts connections.
8. `Query the running PostgreSQL server version` uses `runuser` as root to
   connect locally with `psql` as the `postgres` OS account and run
   `SHOW server_version_num`. It retries briefly while the server starts and
   marks the read-only query as unchanged. This also detects a missing or
   unavailable local cluster.
9. `Verify PostgreSQL 17 is serving local connections` asserts that the
   queried server's major version is 17. A connection failure or different
   version fails the playbook instead of reporting a successful install.

The SQL check validates the **server**. `psql --version` alone reports the
client version and cannot prove that the database is running.

## Run and verify

From the workspace root in WSL, after setting `ANSIBLE_CONFIG`, run:

```bash
ansible-playbook playbooks/postgresql.yml
```

Success means the final version assertion passes and the recap shows
`failed=0` and `unreachable=0`. A second run should report `changed=0` when
nothing has drifted. This JFrog configuration has not been run on the VM yet;
verify repository access, indexing, and signing before installation.

For an independent check, SSH to the VM and run:

```bash
pg_lsclusters
sudo -u postgres psql -XAt -d postgres -c 'SHOW server_version;'
dpkg-query -W postgresql-17
```

Expect `17/main` to be `online`, a reported server version beginning with
`17.`, and an installed `postgresql-17` package. You can run the local SQL
query without opening PostgreSQL to the network. Later database access and
backup policy are separate configuration steps.