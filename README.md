---
title: PostgreSQL 17 Ansible lab
description: Install PostgreSQL 17 on the Debian 13 GCP lab VM from JFrog Artifactory.
---

## PostgreSQL lab

The playbook installs PostgreSQL 17.11 and its client and shared packages from
a private JFrog Artifactory Debian APT repository. Provide the repository URL,
signing-key URL, and a read-only JFrog identity to Ansible on the WSL control
node. Debian supplies any remaining dependencies.
PostgreSQL uses its package defaults; this playbook does not expose port 5432.

Run Ansible from WSL Ubuntu, where Ansible is installed. The inventory targets
`postgres17-lab` at its current external IP with the WSL gcloud SSH identity.
Before a future run, verify the IP, SSH user, and identity path in
`inventory/hosts.yml`. First establish WSL's SSH key and trusted host entry
using `gcloud compute ssh` from WSL (the earlier Windows SSH session uses a
different key). Ansible will not silently accept an unknown host key.

```bash
gcloud compute ssh postgres17-lab \
	--project=project-025ac1f2-75d5-497d-a57 \
	--zone=australia-southeast1-b
```

From the repository root inside WSL, set `ANSIBLE_CONFIG` explicitly because
Ansible ignores automatically discovered config files on world-writable
Windows-mounted directories:

```bash
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
ansible-playbook playbooks/postgresql.yml --syntax-check
```

Before installation, export the four JFrog settings described in the
[Ansible workspace guide](docs/ansible-guide.md). The syntax check does not
require credentials. When you are ready to install, run the playbook separately:

```bash
ansible-playbook playbooks/postgresql.yml
```

The role pins the five packages uploaded to JFrog, enables the PostgreSQL service,
and queries the local server as `postgres` to confirm it reports major version
17. A failed connection or mismatched version fails the playbook. Database
users, networking, and authentication are left for later work.

For a step-by-step introduction, see the
[Ansible workspace guide](docs/ansible-guide.md).