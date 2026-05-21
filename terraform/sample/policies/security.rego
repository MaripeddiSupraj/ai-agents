package terraform

import future.keywords.if
import future.keywords.in

# Deny storage buckets that grant public access (allUsers / allAuthenticatedUsers)
deny[msg] {
    resource := input.resources[_]
    resource.type == "google_storage_bucket_iam_member"
    resource.member == "allUsers"
    msg := {
        "policy": "storage_public_access_prohibited",
        "resource": resource.address,
        "message": "Storage bucket IAM grants public access to allUsers. Use signed URLs or VPC-SC perimeters instead.",
        "severity": "CRITICAL",
    }
}

deny[msg] {
    resource := input.resources[_]
    resource.type == "google_storage_bucket_iam_member"
    resource.member == "allAuthenticatedUsers"
    msg := {
        "policy": "storage_public_access_prohibited",
        "resource": resource.address,
        "message": "Storage bucket IAM grants access to allAuthenticatedUsers. Use fine-grained IAM instead.",
        "severity": "HIGH",
    }
}

# Deny IAM policies with overly broad roles (roles/owner, roles/*.admin)
deny[msg] {
    resource := input.resources[_]
    resource.type == "google_project_iam_member"
    resource.role == "roles/owner"
    msg := {
        "policy": "iam_no_owner_role",
        "resource": resource.address,
        "message": "Project IAM binding grants roles/owner. Use roles/viewer or custom roles with least privilege.",
        "severity": "CRITICAL",
    }
}

deny[msg] {
    resource := input.resources[_]
    resource.type == "google_project_iam_member"
    contains(resource.role, "admin")
    msg := {
        "policy": "iam_no_admin_role",
        "resource": resource.address,
        "message": sprintf("IAM binding grants '%s'. Use a scoped role instead.", [resource.role]),
        "severity": "HIGH",
    }
}

# Deny resources missing required labels
required_labels := {"Environment", "Owner", "Name"}

deny[msg] {
    resource := input.resources[_]
    resource.type != "google_service_account"
    resource.type != "google_project_iam_member"
    resource.type != "google_compute_network"
    resource.type != "google_compute_subnetwork"
    resource.type != "google_compute_firewall"
    resource.type != "google_kms_key_ring"
    resource.type != "google_kms_crypto_key"
    missing_label := required_labels[_]
    not resource.labels[missing_label]
    msg := {
        "policy": "required_labels_missing",
        "resource": resource.address,
        "message": sprintf("Missing required label '%s'. All resources must have labels: Environment, Owner, Name.", [missing_label]),
        "severity": "MEDIUM",
    }
}

# Deny Cloud NAT gateways (cost control)
deny[msg] {
    resource := input.resources[_]
    resource.type == "google_compute_router_nat"
    msg := {
        "policy": "cost_control_cloud_nat",
        "resource": resource.address,
        "message": "Cloud NAT detected (~$32/month). Consider using Private Google Access or VPC-SC to reduce costs.",
        "severity": "MEDIUM",
    }
}
