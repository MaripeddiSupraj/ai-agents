package terraform

import future.keywords.if
import future.keywords.in

# Flag large EC2 instance types (cost control)
deny[msg] {
    resource := input.resources[_]
    resource.type == "aws_instance"
    instance_type := resource.instance_type
    startswith(instance_type, "m5.") or
    startswith(instance_type, "c5.") or
    startswith(instance_type, "r5.") or
    startswith(instance_type, "t3.large")
    msg := {
        "policy": "cost_control_ec2_instance_type",
        "resource": resource.address,
        "message": sprintf("EC2 instance type '%s' may be oversized. Consider right-sizing or using Graviton (t4g/m7g).", [instance_type]),
        "severity": "LOW",
    }
}

# Flag RDS instances not using Aurora serverless
deny[msg] {
    resource := input.resources[_]
    resource.type == "aws_db_instance"
    not resource.engine == "aurora"
    msg := {
        "policy": "cost_control_rds_aurora",
        "resource": resource.address,
        "message": "RDS instance not using Aurora. Consider Aurora Serverless v2 for cost efficiency.",
        "severity": "LOW",
    }
}
