package terraform

required_labels := {"environment", "owner", "name"}

deny contains msg if {
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

deny contains msg if {
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

deny contains msg if {
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

deny contains msg if {
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

deny contains msg if {
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
        "message": sprintf("Missing required label '%s'. All resources must have labels: environment, owner, name.", [missing_label]),
        "severity": "MEDIUM",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_compute_router_nat"
    msg := {
        "policy": "cost_control_cloud_nat",
        "resource": resource.address,
        "message": "Cloud NAT detected (~$32/month). Consider using Private Google Access or VPC-SC to reduce costs.",
        "severity": "MEDIUM",
    }
}
