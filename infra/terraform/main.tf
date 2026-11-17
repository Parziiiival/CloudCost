# SAMPLE ONLY - for cost estimation with Infracost. Do not `terraform apply`:
# applying this would create paid AWS resources.
#
#   infracost breakdown --path infra/terraform --format json --out-file infracost.json
#
# then upload infracost.json on the Estimates page. sample_data/infracost_sample.json
# is a pre-generated example so the feature works without Infracost installed.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region                      = "us-east-1"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}

variable "db_password" {
  description = "Never hard-code this. Only needed if the plan were ever applied."
  type        = string
  sensitive   = true
  default     = null
}

resource "aws_instance" "web" {
  ami           = "ami-0123456789abcdef0" # placeholder
  instance_type = "t3.large"

  root_block_device {
    volume_type = "gp3"
    volume_size = 88
  }

  tags = { Name = "web", Project = "cloudcost-sample" }
}

resource "aws_db_instance" "main" {
  identifier                  = "cloudcost-sample"
  engine                      = "postgres"
  instance_class              = "db.t3.medium"
  allocated_storage           = 100
  storage_type                = "gp3"
  username                    = "app"
  password                    = var.db_password
  skip_final_snapshot         = true
}
