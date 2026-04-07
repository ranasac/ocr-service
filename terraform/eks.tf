module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Expose the API server publicly so you can run kubectl from your machine.
  # Restrict to your IP in production: cluster_endpoint_public_access_cidrs = ["x.x.x.x/32"]
  cluster_endpoint_public_access = true

  eks_managed_node_groups = {

    # ── General nodes: ocr-service, consumer, Kafka, MongoDB, Redis ──────────
    general = {
      name           = "general"
      instance_types = var.general_node_instance_types
      min_size       = var.general_node_min
      max_size       = var.general_node_max
      desired_size   = var.general_node_desired

      labels = {
        workload = "general"
      }
    }

    # ── ML inference nodes: ocr-ml-service ───────────────────────────────────
    # Tainted so only pods that explicitly tolerate "workload=ml-inference"
    # are scheduled here. Keeps inference latency predictable by preventing
    # general workloads from competing for CPU.
    ml = {
      name           = "ml"
      instance_types = var.ml_node_instance_types
      min_size       = var.ml_node_min
      max_size       = var.ml_node_max
      desired_size   = var.ml_node_desired

      labels = {
        workload = "ml-inference"
      }

      taints = [
        {
          key    = "workload"
          value  = "ml-inference"
          effect = "NO_SCHEDULE"
        }
      ]
    }
  }
}
