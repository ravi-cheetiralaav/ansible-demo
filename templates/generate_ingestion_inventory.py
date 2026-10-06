"""Generate a single-sheet GDC application ingestion inventory template (Jira example)."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

OUTPUT = Path(__file__).parent / "gdc-app-ingestion-inventory.xlsx"
BLANK_ROWS = 60
EXAMPLE_FONT = Font(color="FF0000")
WRAP = Alignment(wrap_text=True, vertical="top")

# (header, width, description, lookup list name or None)
COLUMNS: list[tuple[str, int, str, str | None]] = [
    ("S.No", 6, "Sequence number", None),
    ("Tool Name", 14, "Application / product being onboarded", None),
    ("Component", 24, "Logical piece of the tool (app, database, storage, config)", None),
    ("Component Role", 16, "What the component does for the tool", "Role"),
    ("Hosting Platform VM/K8s", 16, "Where it runs on GDC", "Platform"),
    ("Deployment Method", 18, "How it is deployed", "DeployMethod"),
    ("Artifact Type", 18, "Type of artifact that must be ingested into JFrog", "ArtifactType"),
    ("Artifact Name / Coordinates", 34, "Chart, image, package, provider or module name", None),
    ("Version", 16, "Exact version / tag to ingest (no 'latest')", None),
    ("Upstream Source (URL / Registry)", 34, "Where the platform team pulls it from", None),
    ("Provided By", 14, "Vendor / OSS / Internal", "ProvidedBy"),
    ("JFrog Repo Type", 14, "Remote (proxy) / Local (upload) / Virtual", "RepoType"),
    ("JFrog Repo Key", 26, "Target repository in JFrog", None),
    ("Transitive Dependencies", 34, "Images / packages pulled in by this artifact (e.g. images referenced by a Helm chart)", None),
    ("Infra Provisioning (Day 0/1)", 30, "How the underlying infra is created (Terraform module / platform service)", None),
    ("How does Day 2 Managed?", 34, "Ongoing configuration: Terraform provider, Ansible, Helm upgrade, manual", None),
    ("Terraform Provider / Module & Version", 30, "Providers and modules that must be mirrored in JFrog", None),
    ("Depends On (S.No)", 12, "Rows this component needs first", None),
    ("Sizing (CPU / RAM / Storage)", 24, "Per instance and count", None),
    ("Ports / Endpoints", 18, "Listening ports and URLs", None),
    ("Secrets Required (reference only)", 28, "Secret names / Vault paths, never values", None),
    ("Environments", 14, "Dev / Test / Prod", "Environment"),
    ("License", 16, "Licence type", None),
    ("Owner", 16, "Responsible team", None),
    ("Comments", 34, "Assumptions, open questions, constraints", None),
]

LOOKUPS: dict[str, list[str]] = {
    "Role": ["Application", "Database", "Storage", "Cache / Queue", "Ingress / Networking", "Configuration (Day 2)", "Monitoring", "Other"],
    "Platform": ["Kubernetes", "VM", "Kubernetes + VM", "Terraform only", "Platform Service"],
    "DeployMethod": ["Helm Chart", "Docker Image (manifests)", "Ansible", "Terraform", "Manual"],
    "ArtifactType": [
        "Helm Chart", "Docker Image", "Debian Package", "RPM Package", "Ansible Role",
        "Ansible Collection", "Terraform Provider", "Terraform Module", "VM Image", "Generic Binary",
    ],
    "ProvidedBy": ["Vendor", "Open Source", "Internal"],
    "RepoType": ["Remote", "Local", "Virtual"],
    "Environment": ["Dev", "Test", "Prod", "Dev, Test, Prod"],
}

JIRA_ROWS: list[list[str]] = [
    ["1", "Jira", "Jira Application", "Application", "Kubernetes", "Helm Chart", "Helm Chart",
     "atlassian-data-center/jira", "1.x (confirm)", "https://atlassian.github.io/data-center-helm-charts",
     "Vendor", "Remote", "helm-virtual", "Images: atlassian/jira-software (S.No 2), alpine init container (S.No 3)",
     "Namespace + quotas via Terraform (kubernetes provider)", "Helm upgrade via pipeline; projects/groups via Terraform (S.No 9)",
     "hashicorp/kubernetes <ver>", "4, 6, 7", "2 vCPU / 4Gi per pod; Prod 2 replicas", "8080 (http), 40001/40011 (cluster)",
     "jira-db-credentials, jira-license, jira-tls", "Dev, Test, Prod", "Commercial", "Collab Tools", "Sample Row - vendor Helm chart"],
    ["2", "Jira", "Jira Application Image", "Application", "Kubernetes", "Helm Chart", "Docker Image",
     "atlassian/jira-software", "10.3.x (confirm)", "docker.io", "Vendor", "Remote", "docker-virtual", "",
     "", "Image tag bumped in Helm values", "", "1", "", "", "jfrog-pull (imagePullSecret)", "Dev, Test, Prod",
     "Commercial", "Collab Tools", "Override image.repository to JFrog; pin by digest"],
    ["3", "Jira", "Init Container Image", "Application", "Kubernetes", "Helm Chart", "Docker Image",
     "alpine", "<pinned tag>", "docker.io", "Open Source", "Remote", "docker-virtual", "",
     "", "Helm values", "", "1", "", "", "", "Dev, Test, Prod", "MIT", "Collab Tools",
     "Used by shared-home permission fixer; confirm with 'helm template'"],
    ["4", "Jira", "Database (PostgreSQL 17)", "Database", "VM", "Ansible", "Debian Package",
     "postgresql-17, postgresql-client-17", "17.x (pinned)", "https://apt.postgresql.org/pub/repos/apt",
     "Open Source", "Remote", "debian-virtual", "PGDG signing key (generic-local); Ansible collection (S.No 5)",
     "VM provisioned via Terraform (platform gdc-vm module)", "Ansible: config, patching, backups (pgBackRest)",
     "platform/gdc-vm <ver>", "", "4 vCPU / 16 GiB / 200 GiB data; Prod primary + standby", "5432",
     "Vault: secret/apps/jira/<env>/db", "Dev, Test, Prod", "PostgreSQL License", "Platform DBA",
     "GDC has no PostgreSQL 17 service; confirm Jira supports PG 17"],
    ["5", "Jira", "Database Config Automation", "Database", "VM", "Ansible", "Ansible Collection",
     "community.postgresql", "<pinned>", "https://galaxy.ansible.com", "Open Source", "Remote", "ansible-virtual",
     "", "", "Used by roles/postgresql playbook", "", "4", "", "", "", "Dev, Test, Prod", "GPL-3.0", "Platform DBA", ""],
    ["6", "Jira", "Shared Home Storage", "Storage", "Platform Service", "Terraform", "Terraform Module",
     "RWX storage class / volume", "", "GDC platform", "Internal", "Local", "terraform-modules-local", "",
     "PVC via Helm values on RWX StorageClass", "Capacity expansion via platform request", "", "", "100 GiB RWX", "",
     "", "Dev, Test, Prod", "N/A", "Platform Team", "Required for Jira Data Center clustering"],
    ["7", "Jira", "Object Storage (attachments)", "Storage", "Platform Service", "Terraform", "Terraform Provider",
     "GDC object storage bucket", "", "GDC platform", "Internal", "Local", "terraform-virtual", "",
     "Bucket + access key via Terraform", "Terraform (lifecycle / retention)", "<GDC storage provider> <ver>", "",
     "500 GiB", "S3 API 443", "Vault: secret/apps/jira/<env>/s3", "Dev, Test, Prod", "N/A", "Platform Team",
     "Optional; confirm Jira version supports S3 attachment storage"],
    ["8", "Jira", "GitLab Onboarding (repos & groups)", "Configuration (Day 2)", "Terraform only", "Terraform",
     "Terraform Provider", "gitlabhq/gitlab", "<pinned>", "registry.terraform.io", "Open Source", "Remote",
     "terraform-virtual", "", "", "Terraform will be used to onboard repos and projects", "gitlabhq/gitlab <ver>", "",
     "", "443", "Vault: secret/platform/gitlab/tf", "Dev, Test, Prod", "MPL-2.0", "Platform Team",
     "Repo for Jira Helm values + Terraform"],
    ["9", "Jira", "Jira Projects / Groups Config", "Configuration (Day 2)", "Terraform only", "Terraform",
     "Terraform Provider", "fourplusone/jira (community - confirm)", "<pinned>", "registry.terraform.io",
     "Open Source", "Remote", "terraform-virtual", "", "", "Terraform creates Jira projects, groups, memberships",
     "fourplusone/jira <ver>", "1", "", "443 (Jira REST API)", "Vault: secret/apps/jira/<env>/tf-admin",
     "Dev, Test, Prod", "MPL-2.0", "Collab Tools", "Community provider - needs security review"],
]


def build_inventory(wb: Workbook) -> None:
    ws = wb.active
    ws.title = "Ingestion_Inventory"
    ws.append([c[0] for c in COLUMNS])
    for row in JIRA_ROWS:
        ws.append(row)
        for cell in ws[ws.max_row]:
            cell.font = EXAMPLE_FONT
            cell.alignment = WRAP
    last_row = 1 + len(JIRA_ROWS) + BLANK_ROWS
    for r in range(len(JIRA_ROWS) + 2, last_row + 1):
        ws.cell(row=r, column=1, value=r - 1)

    for idx, (_, width, _, _) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    for cell in ws[1]:
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[1].height = 36

    table = Table(displayName="IngestionInventory", ref=f"A1:{get_column_letter(len(COLUMNS))}{last_row}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=False)
    ws.add_table(table)
    ws.freeze_panes = "C2"

    lookup_names = list(LOOKUPS)
    for idx, (_, _, _, lookup) in enumerate(COLUMNS, start=1):
        if lookup:
            src = get_column_letter(lookup_names.index(lookup) + 1)
            dv = DataValidation(type="list", formula1=f"=Lookups!${src}$2:${src}${len(LOOKUPS[lookup]) + 1}",
                                allow_blank=True, showErrorMessage=False)
            col = get_column_letter(idx)
            dv.add(f"{col}2:{col}{last_row}")
            ws.add_data_validation(dv)


def build_guide(wb: Workbook) -> None:
    ws = wb.create_sheet("Column_Guide")
    ws.append(["Column", "What to enter", "Mandatory"])
    mandatory = {"Tool Name", "Component", "Hosting Platform VM/K8s", "Deployment Method", "Artifact Type",
                 "Artifact Name / Coordinates", "Version", "Upstream Source (URL / Registry)",
                 "How does Day 2 Managed?", "Environments", "Owner"}
    for name, _, desc, _ in COLUMNS:
        ws.append([name, desc, "Yes" if name in mandatory else "No"])
    ws.append([])
    ws.append(["Rules", "One row per artifact that must be ingested into JFrog. Red rows are the Jira sample - replace them."])
    ws.append(["", "List every image a Helm chart renders, every OS package, Ansible collection and Terraform provider."])
    ws.append(["", "Pin exact versions. Never enter secret values - only the Vault path / secret name."])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 100
    ws.column_dimensions["C"].width = 12


def build_lookups(wb: Workbook) -> None:
    ws = wb.create_sheet("Lookups")
    for col, (name, values) in enumerate(LOOKUPS.items(), start=1):
        ws.cell(row=1, column=col, value=name).font = Font(bold=True)
        for row, value in enumerate(values, start=2):
            ws.cell(row=row, column=col, value=value)
        ws.column_dimensions[get_column_letter(col)].width = 24
    ws.sheet_state = "hidden"


def main() -> None:
    wb = Workbook()
    build_inventory(wb)
    build_guide(wb)
    build_lookups(wb)
    wb.save(OUTPUT)
    print(f"Created {OUTPUT}")


if __name__ == "__main__":
    main()
