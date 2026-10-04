# Paper-only AWS foundation

This is a reviewable **foundation plan**, not a deployed product. It creates EKS Auto Mode and
three private ECR repositories in an existing VPC. It cannot enable live trading. Aurora,
ClickHouse, Redpanda, Temporal Cloud, Valkey, application manifests, Argo CD, Cloudflare and
hosted observability are separate work; no service is made public by this stack.

Before planning, an operator must create an AWS account and IAM Identity Center access, choose
the legal/data-residency region, provide two private subnets in different availability zones with
needed egress or VPC endpoints, a same-region customer-managed KMS key whose policy permits EKS
use, and a tightly controlled operator IAM role. The state
bucket must already exist with versioning, encryption, public-access block and restricted access.
Use one bucket key per environment. Never commit a filled backend file or a plan/state file.

After installing OpenTofu 1.12+ and configuring short-lived AWS access:

```text
tofu init -backend-config=backend.hcl
tofu fmt -check
tofu validate
tofu plan -var-file=paper.tfvars -out=paper.tfplan
```

Review the complete plan and IAM permissions before an authorized apply. The cluster API is
private-only and grants initial admin access solely to the supplied operator role. CI has no
cluster-admin access or long-lived AWS keys. Container tags are immutable, scan on push is on,
and ECR uses AWS-managed KMS encryption. EKS API data uses the supplied customer-managed key;
its key policy and recovery lifecycle require review. Images should later be deployed by
immutable digest.

The first application deployment remains blocked on real Clerk token verification, managed
stateful services, secret delivery, network policies, signed image delivery, provider rights,
runbooks and an independent security review. Do not infer release readiness from a successful
foundation plan.

Source checks (2026-10-04): [AWS EKS Auto Mode requirements](https://docs.aws.amazon.com/eks/latest/userguide/create-cluster-auto.html),
[AWS Auto Mode IAM roles](https://docs.aws.amazon.com/eks/latest/userguide/auto-cluster-iam-role.html),
[AWS provider EKS schema](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_cluster),
[EKS default envelope encryption and customer-managed keys](https://docs.aws.amazon.com/eks/latest/userguide/envelope-encryption.html),
and [OpenTofu S3 locking](https://opentofu.org/docs/language/settings/backends/s3/).
