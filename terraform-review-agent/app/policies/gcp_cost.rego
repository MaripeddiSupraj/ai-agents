package terraform

# ─── GCP Cost Control Policies ────────────────────────────────────────────────
# Flag high-cost or unexpectedly expensive resource configurations.

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_compute_router_nat"
    msg := {
        "policy":   "gcp_cost_cloud_nat",
        "resource": resource.address,
        "message":  "Cloud NAT detected (~$32/month minimum). Consider Private Google Access or VPC-SC to avoid NAT costs.",
        "severity": "MEDIUM",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_compute_instance"
    machine_type := resource.machine_type
    large_prefixes := ["n2-standard-", "n2-highmem-", "n2-highcpu-", "c2-standard-", "c2d-standard-", "m1-megamem-", "m1-ultramem-"]
    some prefix in large_prefixes
    startswith(machine_type, prefix)
    msg := {
        "policy":   "gcp_cost_oversized_instance",
        "resource": resource.address,
        "message":  sprintf("Instance type '%s' may be oversized. Consider e2-small or e2-micro for non-production workloads.", [machine_type]),
        "severity": "LOW",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_container_cluster"
    msg := {
        "policy":   "gcp_cost_gke_cluster",
        "resource": resource.address,
        "message":  "GKE cluster creation detected (~$73+/month for control plane + nodes). Verify cluster tier and node counts.",
        "severity": "MEDIUM",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_sql_database_instance"
    msg := {
        "policy":   "gcp_cost_cloud_sql",
        "resource": resource.address,
        "message":  "Cloud SQL instance detected (~$50+/month). Verify instance tier and HA settings for environment.",
        "severity": "LOW",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_compute_forwarding_rule"
    msg := {
        "policy":   "gcp_cost_forwarding_rule",
        "resource": resource.address,
        "message":  "Load balancer forwarding rule detected (~$18/month). Ensure this is necessary for the environment.",
        "severity": "LOW",
    }
}
