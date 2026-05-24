package terraform

# ─── AWS Security Policies ────────────────────────────────────────────────────
# Covers common AWS misconfigurations. Pair with aws_cost.rego for full coverage.

aws_required_tags := {"Environment", "Owner", "Name"}

aws_tag_exempt := {
    "aws_iam_role",
    "aws_iam_policy",
    "aws_iam_role_policy_attachment",
    "aws_iam_user_policy",
    "aws_route53_zone",
    "aws_route53_record",
}

# ── S3 Public Access ───────────────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_s3_bucket_acl"
    resource.labels["acl"] == "public-read"
    msg := {
        "policy":   "aws_s3_no_public_read_acl",
        "resource": resource.address,
        "message":  "S3 bucket ACL set to public-read. Use bucket policies with explicit conditions instead.",
        "severity": "CRITICAL",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_s3_bucket_acl"
    resource.labels["acl"] == "public-read-write"
    msg := {
        "policy":   "aws_s3_no_public_write_acl",
        "resource": resource.address,
        "message":  "S3 bucket ACL set to public-read-write. This allows unauthenticated writes — remove immediately.",
        "severity": "CRITICAL",
    }
}

# ── IAM Privilege Escalation ───────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_iam_user"
    msg := {
        "policy":   "aws_iam_no_iam_users",
        "resource": resource.address,
        "message":  "IAM user detected. Use IAM roles with temporary credentials or AWS SSO instead of long-lived user keys.",
        "severity": "HIGH",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_iam_access_key"
    msg := {
        "policy":   "aws_iam_no_access_keys",
        "resource": resource.address,
        "message":  "IAM access key detected. Use IAM roles and instance profiles to avoid long-lived credentials.",
        "severity": "CRITICAL",
    }
}

# ── Security Group Rules ───────────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_security_group_rule"
    resource.labels["type"] == "ingress"
    resource.labels["cidr_blocks"] == "0.0.0.0/0"
    resource.labels["from_port"] == "22"
    msg := {
        "policy":   "aws_sg_no_open_ssh",
        "resource": resource.address,
        "message":  "Security group allows SSH (port 22) from 0.0.0.0/0. Restrict to known IP ranges or use SSM Session Manager.",
        "severity": "CRITICAL",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_security_group_rule"
    resource.labels["type"] == "ingress"
    resource.labels["cidr_blocks"] == "0.0.0.0/0"
    resource.labels["from_port"] == "3389"
    msg := {
        "policy":   "aws_sg_no_open_rdp",
        "resource": resource.address,
        "message":  "Security group allows RDP (port 3389) from 0.0.0.0/0. Restrict to known IPs or use AWS Systems Manager.",
        "severity": "CRITICAL",
    }
}

# ── Required Tags ──────────────────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    startswith(resource.type, "aws_")
    not aws_tag_exempt[resource.type]
    missing_tag := aws_required_tags[_]
    not resource.labels[missing_tag]
    msg := {
        "policy":   "aws_required_tags_missing",
        "resource": resource.address,
        "message":  sprintf("Missing required tag '%s'. All AWS resources must have: Environment, Owner, Name.", [missing_tag]),
        "severity": "MEDIUM",
    }
}

# ── Encryption ─────────────────────────────────────────────────────────────────

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_ebs_volume"
    not resource.labels["encrypted"]
    msg := {
        "policy":   "aws_ebs_encryption_required",
        "resource": resource.address,
        "message":  "EBS volume is not encrypted. Set encrypted = true or use an encrypted AMI.",
        "severity": "HIGH",
    }
}

deny contains msg if {
    resource := input.resources[_]
    resource.type == "aws_rds_instance"
    not resource.labels["storage_encrypted"]
    msg := {
        "policy":   "aws_rds_encryption_required",
        "resource": resource.address,
        "message":  "RDS instance storage is not encrypted. Set storage_encrypted = true.",
        "severity": "HIGH",
    }
}
