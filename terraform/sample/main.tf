terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_s3_bucket" "public_data" {
  bucket = "my-org-public-data-1234"
  acl    = "public-read"

  tags = {
    Name = "Public data bucket"
  }
}

resource "aws_s3_bucket_public_access_block" "public_data_block" {
  bucket = aws_s3_bucket.public_data.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_iam_role" "lambda_role" {
  name = "lambda-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_admin_policy" {
  name = "lambda-admin-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = "*"
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}

resource "aws_s3_bucket" "app_logs" {
  bucket = "my-org-app-logs"
  acl    = "private"

  tags = {
    Name        = "Application logs"
    Environment = "production"
    Owner       = "platform-team"
  }
}

resource "aws_s3_bucket_public_access_block" "app_logs_block" {
  bucket = aws_s3_bucket.app_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "users_table" {
  name         = "users-table"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"

  attribute {
    name = "user_id"
    type = "S"
  }
}

resource "aws_lambda_function" "data_processor" {
  function_name = "data-processor"
  role          = aws_iam_role.lambda_role.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.11"
  filename      = "function.zip"
  timeout       = 30

  environment {
    variables = {
      LOG_LEVEL = "INFO"
    }
  }
}

resource "aws_nat_gateway" "main" {
  allocation_id = "eipalloc-12345678"
  subnet_id     = "subnet-12345678"
}

resource "aws_instance" "bastion" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.medium"

  tags = {
    Name = "bastion-host"
  }
}
