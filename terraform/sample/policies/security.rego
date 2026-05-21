package terraform

import future.keywords.if
import future.keywords.in

# Deny S3 buckets that do not have public access block enabled
deny[msg] {
    resource := input.resources[_]
    resource.type == "aws_s3_bucket"
    resource.public_access_blocked == false
    msg := {
        "policy": "s3_public_access_block_required",
        "resource": resource.address,
        "message": "S3 bucket must have public access block enabled. Use aws_s3_bucket_public_access_block.",
        "severity": "HIGH",
    }
}

# Deny IAM policies with wildcard actions
deny[msg] {
    resource := input.resources[_]
    resource.type == "aws_iam_role_policy"
    contains(resource.policy_json, "*")
    msg := {
        "policy": "iam_no_wildcard_actions",
        "resource": resource.address,
        "message": "IAM policy should not contain wildcard (*) actions. Use least-privilege permissions.",
        "severity": "CRITICAL",
    }
}

# Deny resources missing required tags
required_tags := {"Environment", "Owner", "Name"}

deny[msg] {
    resource := input.resources[_]
    resource.type != "aws_iam_role"
    resource.type != "aws_iam_role_policy"
    resource.type != "aws_iam_user"
    resource.type != "aws_iam_policy"
    missing_tag := required_tags[_]
    not resource.tags[missing_tag]
    msg := {
        "policy": "required_tags_missing",
        "resource": resource.address,
        "message": sprintf("Missing required tag '%s'. All resources must have tags: Environment, Owner, Name.", [missing_tag]),
        "severity": "MEDIUM",
    }
}

# Deny NAT gateways (cost control)
deny[msg] {
    resource := input.resources[_]
    resource.type == "aws_nat_gateway"
    msg := {
        "policy": "cost_control_nat_gateway",
        "resource": resource.address,
        "message": "NAT Gateway detected (~$32/month). Consider using NAT instance or VPC endpoints for cost savings.",
        "severity": "MEDIUM",
    }
}
