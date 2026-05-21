package terraform

import future.keywords.if
import future.keywords.in

# Flag large Compute Engine machine types (cost control)
deny[msg] {
    resource := input.resources[_]
    resource.type == "google_compute_instance"
    machine_type := resource.machine_type
    startswith(machine_type, "n2-") or
    startswith(machine_type, "c2-") or
    startswith(machine_type, "m1-") or
    startswith(machine_type, "e2-standard-")
    msg := {
        "policy": "cost_control_machine_type",
        "resource": resource.address,
        "message": sprintf("Instance uses '%s' which may be oversized. Consider e2-small or e2-micro for non-production.", [machine_type]),
        "severity": "LOW",
    }
}

# Flag non-serverless Cloud SQL
deny[msg] {
    resource := input.resources[_]
    resource.type == "google_sql_database_instance"
    resource.database_version != "SQLSERVER_2019_STANDARD"
    resource.database_version != "POSTGRES_15"
    msg := {
        "policy": "cost_control_sql_edition",
        "resource": resource.address,
        "message": "Cloud SQL not using latest edition. Consider using Cloud SQL Enterprise Plus for better price/performance.",
        "severity": "LOW",
    }
}
