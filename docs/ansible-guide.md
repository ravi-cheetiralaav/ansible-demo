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

This lab installs PostgreSQL 17.11 from a private Google Artifact Registry
(GAR) APT repository. It keeps PostgreSQL's default local-only access; it does
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
  holds the GAR project, region, repository, and exact package versions. These
  are role variables used by the tasks.
* [roles/postgresql/tasks/main.yml](../roles/postgresql/tasks/main.yml) contains
  the installation and post-install validation tasks in execution order.
* [README.md](../README.md) is the short project overview.

## Prerequisites

* Use WSL Ubuntu with Ansible Core 2.16 or newer, `gcloud`, and an SSH client.
  Run the commands below inside WSL, not in the Windows PowerShell shell.
* The existing `postgres17-lab` VM must be running in
  `australia-southeast1-b` on Debian 13 amd64, with Python 3 and passwordless
  sudo available to the SSH user.
* The VM service account needs Artifact Registry Reader on the private
  `postgres-debs` repository in project
  `project-025ac1f2-75d5-497d-a57`, plus the `cloud-platform` API scope.
  The VM needs outbound access to Debian package mirrors, GAR, and Google's
  repository signing-key endpoint.
* SSH to the VM must be allowed from your current public IP. The temporary
  `allow-ssh-local` firewall rule was restricted to a single source `/32`;
  if your IP changes, update that restricted rule before connecting. Do not
  broaden it to the entire internet.
* Compare the VM's current external IP and SSH identity with
  [inventory/hosts.yml](../inventory/hosts.yml). Its current address is
  `34.40.252.185`. If the VM is recreated, the host-key alias and known-host
  entry may also change. Do not turn off host-key checking to work around a
  mismatch; verify the new VM identity first.
* The GAR repository must contain the pinned packages listed in the role
  defaults. Standard Debian repositories provide other dependencies. No
  service-account key file is needed on the VM: GAR's APT credential helper
  uses its attached service account.

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
2. `Install Artifact Registry repository signing key` downloads Google's
   GAR APT signing key over HTTPS to the path later named by `signed-by`.
   APT uses it to verify repository metadata.
3. `Install Artifact Registry APT credential helper` installs
   `apt-transport-artifact-registry` from the VM's existing package sources.
   The helper authenticates requests to the private repository with the VM
   service account; it does not hold a static credential in this workspace.
4. `Configure PostgreSQL Artifact Registry repository` creates a dedicated
   APT source for `postgres-debs` using the authenticated `ar+https` transport
   and the signing key. The file is owned by root and readable by APT.
5. `Install PostgreSQL 17 packages` refreshes the package index after adding
   the repository, then installs the five exact versions in role defaults:
   server, client, common packages, and `libpq5`. APT resolves additional
   dependencies from Debian. Refreshing here matters because the first APT
   update happened before the GAR source existed on a new VM.
6. `Enable and start PostgreSQL` makes the PostgreSQL service start now and
   after reboot. A running service by itself does not prove the database
   accepts connections.
7. `Query the running PostgreSQL server version` uses `runuser` as root to
   connect locally with `psql` as the `postgres` OS account and run
   `SHOW server_version_num`. It retries briefly while the server starts and
   marks the read-only query as unchanged. This also detects a missing or
   unavailable local cluster.
8. `Verify PostgreSQL 17 is serving local connections` asserts that the
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
nothing has drifted. The playbook was successfully run on this VM, and its
second successful run reported nine `ok` tasks with zero changes.

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