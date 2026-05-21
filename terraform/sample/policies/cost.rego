package terraform

large_types := {"n2-standard-", "n2-highmem-", "n2-highcpu-", "c2-standard-", "c2d-standard-", "m1-megamem-", "m1-ultramem-", "e2-standard-2", "e2-standard-4", "e2-standard-8", "e2-standard-16"}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_compute_instance"
    machine_type := resource.machine_type
    some prefix in large_types
    startswith(machine_type, prefix)
    msg := {
        "policy": "cost_control_machine_type",
        "resource": resource.address,
        "message": sprintf("Instance uses '%s' which may be oversized. Consider e2-small or e2-micro for non-production.", [machine_type]),
        "severity": "LOW",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "google_sql_database_instance"
    not startswith(resource.database_version, "POSTGRES_15")
    msg := {
        "policy": "cost_control_sql_edition",
        "resource": resource.address,
        "message": "Cloud SQL not using latest edition. Consider using Cloud SQL Enterprise Plus for better price/performance.",
        "severity": "LOW",
    }
}
