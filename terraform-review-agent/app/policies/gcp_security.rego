package terraform

# ─── GCP Security Policies ────────────────────────────────────────────────────
# These policies are bundled with the agent and run on every plan.
# Users may add additional .rego files to override or extend these.

required_labels := {"environment", "owner", "name"}

# Resources exempt from label enforcement (infrastructure primitives)
label_exempt := {
    "google_service_account",
    "google_project_iam_member",
    "google_project_iam_binding",
    "google_project_iam_policy",
    "google_storage_bucket_iam_member",
    "google_storage_bucket_iam_binding",
    "google_compute_network",
    "google_compute_subnetwork",
    "google_compute_firewall",
    "google_kms_key_ring",
    "google_kms_crypto_key",
    "google_dns_managed_zone",
    "google_dns_record_set",
    "google_secret_manager_secret",
    "google_secret_manager_secret_version",
    "google_pubsub_topic",
    "google_pubsub_subscription",
    "google_logging_project_sink",
}

# ── Public Access ──────────────────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_storage_bucket_iam_member"
    resource.member == "allUsers"
    msg := {
        "policy":   "gcp_storage_public_access_prohibited",
        "resource": resource.address,
        "message":  "Storage bucket IAM grants public access to allUsers. Use signed URLs or VPC-SC instead.",
        "severity": "CRITICAL",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_storage_bucket_iam_member"
    resource.member == "allAuthenticatedUsers"
    msg := {
        "policy":   "gcp_storage_public_auth_users",
        "resource": resource.address,
        "message":  "Storage bucket IAM grants access to allAuthenticatedUsers. Use fine-grained IAM bindings.",
        "severity": "HIGH",
    }
}

# ── IAM Privilege Escalation ───────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_project_iam_member"
    resource.role == "roles/owner"
    msg := {
        "policy":   "gcp_iam_no_owner_role",
        "resource": resource.address,
        "message":  "Project IAM binding grants roles/owner. Use principle of least privilege with scoped roles.",
        "severity": "CRITICAL",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_project_iam_member"
    resource.role == "roles/editor"
    msg := {
        "policy":   "gcp_iam_no_editor_role",
        "resource": resource.address,
        "message":  "Project IAM binding grants roles/editor which allows broad write access. Use a custom role.",
        "severity": "HIGH",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_project_iam_member"
    contains(resource.role, "admin")
    not resource.role == "roles/storage.objectAdmin"
    msg := {
        "policy":   "gcp_iam_no_admin_role",
        "resource": resource.address,
        "message":  sprintf("IAM binding grants admin role '%s'. Use a scoped, least-privilege role instead.", [resource.role]),
        "severity": "HIGH",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_project_iam_binding"
    resource.role == "roles/owner"
    msg := {
        "policy":   "gcp_iam_binding_no_owner_role",
        "resource": resource.address,
        "message":  "Project IAM binding sets roles/owner. This replaces existing owners. Use additive members only.",
        "severity": "CRITICAL",
    }
}

# ── Service Account Keys ───────────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_service_account_key"
    msg := {
        "policy":   "gcp_no_service_account_keys",
        "resource": resource.address,
        "message":  "Service account key detected. Use Workload Identity Federation or IAM impersonation instead.",
        "severity": "HIGH",
    }
}

# ── Required Labels ────────────────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    startswith(resource.type, "google_")
    not label_exempt[resource.type]
    missing_label := required_labels[_]
    not resource.labels[missing_label]
    msg := {
        "policy":   "gcp_required_labels_missing",
        "resource": resource.address,
        "message":  sprintf("Missing required label '%s'. All GCP resources must have: environment, owner, name.", [missing_label]),
        "severity": "MEDIUM",
    }
}

# ── Database Security ──────────────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_sql_database_instance"
    not resource.labels["backup_enabled"]
    msg := {
        "policy":   "gcp_sql_backup_required",
        "resource": resource.address,
        "message":  "Cloud SQL instance has no backup configuration label. Ensure automated backups are enabled.",
        "severity": "HIGH",
    }
}

# ── Firewall Rules ─────────────────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_compute_firewall"
    resource.labels["direction"] == "INGRESS"
    resource.labels["source_ranges"] == "0.0.0.0/0"
    msg := {
        "policy":   "gcp_firewall_no_open_ingress",
        "resource": resource.address,
        "message":  "Firewall rule allows ingress from 0.0.0.0/0. Restrict to known IP ranges.",
        "severity": "HIGH",
    }
}

# ── GKE Security ───────────────────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_container_cluster"
    msg := {
        "policy":   "gcp_gke_review_required",
        "resource": resource.address,
        "message":  "GKE cluster change detected. Verify: private nodes enabled, shielded nodes, network policy, Workload Identity.",
        "severity": "MEDIUM",
    }
}
