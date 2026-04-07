data "aws_availability_zones" "available" {
  state = "available"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.cluster_name}-vpc"
  cidr = var.vpc_cidr

  # Spread across 3 AZs for availability
  azs = slice(data.aws_availability_zones.available.names, 0, 3)

  # Public subnets: used by AWS Load Balancer Controller for internet-facing ALBs
  public_subnets = [for i in range(3) : cidrsubnet(var.vpc_cidr, 8, i)]

  # Private subnets: EKS worker nodes never have public IPs
  private_subnets = [for i in range(3) : cidrsubnet(var.vpc_cidr, 8, i + 10)]

  enable_nat_gateway   = true
  single_nat_gateway   = true  # set to false for multi-AZ HA (higher cost)
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Tags required for EKS to discover subnets when provisioning load balancers
  public_subnet_tags = {
    "kubernetes.io/role/elb"                        = 1
    "kubernetes.io/cluster/${var.cluster_name}"     = "shared"
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"               = 1
    "kubernetes.io/cluster/${var.cluster_name}"     = "shared"
  }
}
