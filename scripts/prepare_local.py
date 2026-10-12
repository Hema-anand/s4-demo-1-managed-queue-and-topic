

"""Prepares the local resources required for deployment.
Creates or reuses the registry repository, log group, cluster and subnet.
Saves their details in local-config.json for later commands.
"""
import json
import subprocess

from scripts.local_cloud import CLUSTER, LOG_GROUP, REPOSITORY, ROOT, aws, execution_role


def main():
    role = execution_role()  
    try:
        repository = aws("ecr", "describe-repositories", "--repository-names", REPOSITORY)["repositories"][0]
    except subprocess.CalledProcessError as error:
        if "RepositoryNotFoundException" not in error.stderr:
            raise
        repository = aws("ecr", "create-repository", "--repository-name", REPOSITORY)["repository"]

    groups = aws("logs", "describe-log-groups", "--log-group-name-prefix", LOG_GROUP)["logGroups"]
    if not any(item["logGroupName"] == LOG_GROUP for item in groups):
        aws("logs", "create-log-group", "--log-group-name", LOG_GROUP)
    aws("ecs", "create-cluster", "--cluster-name", CLUSTER)

    vpcs = aws("ec2", "describe-vpcs", "--filters", "Name=tag:Name,Values=sprint4-demo-vpc")["Vpcs"]
    if vpcs:
        vpc_id = vpcs[0]["VpcId"]
    else:
        vpc_id = aws("ec2", "create-vpc", "--cidr-block", "10.20.0.0/16",
                     "--tag-specifications", "ResourceType=vpc,Tags=[{Key=Name,Value=sprint4-demo-vpc}]")["Vpc"]["VpcId"]
    subnets = aws("ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={vpc_id}",
                  "Name=tag:Name,Values=sprint4-demo-subnet")["Subnets"]
    if subnets:
        subnet_id = subnets[0]["SubnetId"]
    else:
        subnet_id = aws("ec2", "create-subnet", "--vpc-id", vpc_id, "--cidr-block", "10.20.1.0/24",
                        "--tag-specifications", "ResourceType=subnet,Tags=[{Key=Name,Value=sprint4-demo-subnet}]")["Subnet"]["SubnetId"]
    configuration = {"execution_role_arn": role, "repository_uri": repository["repositoryUri"], "subnet_id": subnet_id}
    (ROOT / "local-config.json").write_text(json.dumps(configuration, indent=2), encoding="utf-8")
    print(json.dumps(configuration, indent=2))
    print("Configuration saved to local-config.json. Continue with the README's local deployment steps.")


if __name__ == "__main__":
    main()
