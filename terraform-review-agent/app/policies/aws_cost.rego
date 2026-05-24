package terraform

# ─── AWS Cost Control Policies ────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_instance"
    instance_type := resource.machine_type
    large_prefixes := ["m5.4xlarge", "m5.8xlarge", "m5.12xlarge", "c5.4xlarge", "c5.9xlarge", "r5.4xlarge", "x1.", "x2."]
    some prefix in large_prefixes
    startswith(instance_type, prefix)
    msg := {
        "policy":   "aws_cost_oversized_ec2",
        "resource": resource.address,
        "message":  sprintf("EC2 instance type '%s' may be oversized. Verify sizing for the environment.", [instance_type]),
        "severity": "LOW",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_db_instance"
    msg := {
        "policy":   "aws_cost_rds_instance",
        "resource": resource.address,
        "message":  "RDS instance detected (costs vary by instance class and storage). Verify Multi-AZ and instance class for environment.",
        "severity": "LOW",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_eks_cluster"
    msg := {
        "policy":   "aws_cost_eks_cluster",
        "resource": resource.address,
        "message":  "EKS cluster detected (~$73/month for control plane). Verify node group sizing and instance types.",
        "severity": "MEDIUM",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_nat_gateway"
    msg := {
        "policy":   "aws_cost_nat_gateway",
        "resource": resource.address,
        "message":  "NAT Gateway detected (~$32+/month + data processing). Consider VPC endpoints for AWS services to reduce costs.",
        "severity": "MEDIUM",
    }
}
