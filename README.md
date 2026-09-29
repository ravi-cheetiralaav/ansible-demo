---
title: PostgreSQL 17 Ansible lab
description: Install PostgreSQL 17 on the Debian 13 GCP lab VM from Artifact Registry.
---

## PostgreSQL lab

The playbook installs PostgreSQL 17.11 and its client and shared packages from
the private `postgres-debs` APT repository in Artifact Registry. The VM's attached
service account needs Artifact Registry Reader on that repository and the
`cloud-platform` access scope. Debian supplies any remaining dependencies.
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

When you are ready to install, run the playbook separately:

```bash
ansible-playbook playbooks/postgresql.yml
```

The role pins the five packages uploaded to GAR, enables the PostgreSQL service,
and queries the local server as `postgres` to confirm it reports major version
17. A failed connection or mismatched version fails the playbook. Database
users, networking, and authentication are left for later work.

For a step-by-step introduction, see the
[Ansible workspace guide](docs/ansible-guide.md).