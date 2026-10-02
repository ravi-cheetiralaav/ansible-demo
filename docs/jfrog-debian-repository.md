---
title: JFrog Debian Repository Setup for PostgreSQL Packages
description: How to create a Debian repository in JFrog Artifactory and upload PostgreSQL binary packages for APT-based installation.
author: Ravi Cheetirala
ms.date: 2026-09-30
ms.topic: how-to
keywords:
  - jfrog
  - artifactory
  - debian
  - apt
  - repository
  - deb
estimated_reading_time: 6
---

## Overview

Use a JFrog Artifactory repository of type Debian when you want Debian or Ubuntu hosts to install packages with `apt`. This repository type is the correct choice for `.deb` packages and APT metadata such as `Packages.gz`, `Release`, and signed repository metadata.

For this project, the goal is to publish PostgreSQL 17 `.deb` packages so the Ansible role can install them from a JFrog-hosted APT source.

> [!IMPORTANT]
> Use a Debian repository type, not a Generic repository type, for `apt` clients. A Generic repository can hold files, but it is not the correct repository model for Debian package metadata and APT repository trust.

## Recommended repository type

Create a repository in Artifactory using the following settings:

* Repository type: Local
* Package type: Debian
* Distribution: `trixie`
* Component: `main`
* Architecture: `amd64` or the architecture you package for

This is the standard APT layout for Debian-based systems and matches the setup used by the Ansible role.

## Repository layout

The final repository should look similar to this:

```text
https://<jfrog-host>/artifactory/<repo-name>/
  dists/
    trixie/
      Release
      Release.gpg
      main/
        binary-amd64/
          Packages
          Packages.gz
  pool/
    main/
      p/
        postgresql-17_17.11-1.pgdg13+2_amd64.deb
      p/
        postgresql-client-17_17.11-1.pgdg13+2_amd64.deb
```

The important idea is that APT expects Debian metadata and package indexes, not just raw files sitting in a folder.

## Create the repository in JFrog

The exact labels in the UI can vary slightly by JFrog version, but the form you showed is the correct flow. In the repo creation page:

1. Go to Artifactory and open Repositories.
2. Click New Local Repository.
3. Set the repository kind to Local.
4. Enter a repository key such as `postgresql-debian`.
5. Set the Repository Layout to the Debian-compatible layout your JFrog version provides, often `simple-default`.
6. Fill in the repository description fields if needed.
7. Under GPG Key Pair, either select an existing key pair or configure the repository to use a new one.
8. In the Debian settings area, keep the distribution/component aligned with your package definitions, for example `trixie` and `main`.
9. Save the repository.

> [!NOTE]
> The JFrog form does not always label the package type in the same way you may expect. If you are creating a Debian/apt repository, the key point is that the repository must be a Local repository using the Debian package model and Debian-compatible metadata settings.

## Create a GPG key pair

APT repositories are trusted by the client only when the repository metadata is signed with a GPG key. The private key is used to sign the repository, while the public key is downloaded by the Linux client and stored in `/usr/share/keyrings/`.

Create the key on a Linux machine you trust for signing:

```bash
gpg --batch --generate-key <<EOF
Key-Type: RSA
Key-Length: 4096
Subkey-Type: RSA
Subkey-Length: 4096
Name-Real: PostgreSQL Debian Repo
Name-Email: repo@example.com
Expire-Date: 0
%no-protection
%commit
EOF
```

List the keys to find the generated key ID:

```bash
gpg --list-secret-keys --keyid-format LONG
```

Export the public key that Debian clients will download:

```bash
gpg --armor --export "PostgreSQL Debian Repo <repo@example.com>" > public-key.asc
```

If you also need the private key for signing repository metadata on the release machine:

```bash
gpg --armor --export-secret-keys "PostgreSQL Debian Repo <repo@example.com>" > private-key.asc
```

> [!WARNING]
> Keep the private key secure. Only the public key should be distributed to Debian clients.

After exporting the public key, upload or reference it through the JFrog repository's GPG configuration so the release metadata can be signed correctly.

## Upload the binary packages

You can upload files either from the Artifactory UI or from the JFrog CLI.

### Option 1: Upload from the UI

1. Open the repository you created.
2. Navigate to the repository root.
3. Create folders matching the Debian layout, for example:
   * `pool/main/`
   * `dists/trixie/main/binary-amd64/`
4. Upload each `.deb` file into the relevant folder.
5. If needed, place the packages under a nested path such as `pool/main/p/`.

### Option 2: Upload from the JFrog CLI

Install and configure the JFrog CLI first, then run a command similar to this:

```bash
jf c add myjfrog --url https://<jfrog-host>.jfrog.io --user <user> --password <token>
jf rt upload "./*.deb" postgresql-debian/pool/main/
```

If you want to push to a specific archive path, use a more explicit target such as:

```bash
jf rt upload "./postgresql-17_17.11-1.pgdg13+2_amd64.deb" postgresql-debian/pool/main/p/
```

## Create the Debian metadata

APT does not use raw `.deb` files alone. It expects repository metadata generated in the Debian index format.

This metadata usually includes:

* `Packages`
* `Packages.gz`
* `Release`
* `Release.gpg`

There are two common ways to generate this metadata:

### Best practice for Artifactory-managed Debian repos

Use Artifactory's Debian repository support to generate the metadata automatically when the repo is configured as a Debian package type. In many cases, after upload, Artifactory can expose the APT metadata endpoints automatically.

### Alternative when you manage the repo manually

Use Debian packaging tools such as:

```bash
apt-ftparchive packages ./pool/main > ./dists/trixie/main/binary-amd64/Packages
gzip -9 -c ./dists/trixie/main/binary-amd64/Packages > ./dists/trixie/main/binary-amd64/Packages.gz
```

Then create the release metadata and sign it with a GPG key if required by your environment.

## Signing the repository

For Debian clients to trust the repo, the repository must be signed with a GPG key.

The two values in your Ansible role are:

* `JFROG_DEB_REPO_URL`: the APT repository URL
* `JFROG_DEB_SIGNING_KEY_URL`: the public key URL used to verify the repository

Example values:

```bash
export JFROG_DEB_REPO_URL="https://<jfrog-host>/artifactory/postgresql-debian"
export JFROG_DEB_SIGNING_KEY_URL="https://<jfrog-host>/artifactory/postgresql-debian/public-key.asc"
```

Use a public key that matches the repository host and is trusted by the Debian client.

## Recommended file structure for this project

For a repository dedicated to PostgreSQL 17 packages, a simple structure is:

```text
postgresql-debian/
  dists/
    trixie/
      Release
      Release.gpg
      main/
        binary-amd64/
          Packages
          Packages.gz
  pool/
    main/
      p/
        postgresql-17_17.11-1.pgdg13+2_amd64.deb
      p/
        postgresql-client-17_17.11-1.pgdg13+2_amd64.deb
```

This is the expected layout for an APT repository that your Debian 13 host can consume.

## Test the repository

After publishing the metadata, validate the repository from an Ubuntu or Debian client:

```bash
curl -I https://<jfrog-host>/artifactory/postgresql-debian/dists/trixie/Release
```

Then add the repo entry to a source list:

```bash
echo "deb [signed-by=/usr/share/keyrings/postgresql-jfrog.asc] https://<jfrog-host>/artifactory/postgresql-debian trixie main" > /etc/apt/sources.list.d/postgresql-jfrog.list
```

Update the package index:

```bash
apt update
```

Then install the package:

```bash
apt install postgresql-17
```

## Final recommendation

For this setup, the cleanest and most standard design is:

* Create a Local repository
* Set Package Type to Debian
* Keep the distribution as `trixie`
* Keep the component as `main`
* Upload `.deb` binaries under `pool/main/`
* Generate the Debian metadata so APT can see the repository
* Publish the matching GPG key and configure the client to trust it

This gives you a fully APT-compatible JFrog repository for PostgreSQL packages.
