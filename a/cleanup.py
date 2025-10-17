import boto3
import datetime
from botocore.exceptions import ClientError

# -----------------------------
# Configuration
# -----------------------------
REGION = "us-east-1"
TTL_HOURS = 24

now = datetime.datetime.utcnow()
cutoff = now - datetime.timedelta(hours=TTL_HOURS)

# AWS clients
s3 = boto3.client("s3", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
iam = boto3.client("iam")
sns = boto3.client("sns")
sts = boto3.client("sts")

ACCOUNT_ID = sts.get_caller_identity()["Account"]
print(f"Cleaning up all AWS resources in last {TTL_HOURS} hours for account {ACCOUNT_ID}")

# -----------------------------
# 1. Lambda functions
# -----------------------------
print("\nDeleting Lambda functions...")
for fn in lam.list_functions()["Functions"]:
    created = fn.get("LastModified")  # e.g., '2025-10-17T10:15:30.000+0000'
    created_dt = datetime.datetime.strptime(created.split("+")[0], "%Y-%m-%dT%H:%M:%S.%f")
    if created_dt >= cutoff:
        try:
            lam.delete_function(FunctionName=fn["FunctionName"])
            print(f"Deleted Lambda function: {fn['FunctionName']}")
        except ClientError as e:
            print(f"Failed to delete Lambda {fn['FunctionName']}: {e}")

# -----------------------------
# 2. IAM roles
# -----------------------------
print("\nDeleting IAM roles...")
for role in iam.list_roles()["Roles"]:
    created = role["CreateDate"]
    if created >= cutoff:
        try:
            # Delete inline policies
            for pol in iam.list_role_policies(RoleName=role["RoleName"])["PolicyNames"]:
                iam.delete_role_policy(RoleName=role["RoleName"], PolicyName=pol)
            # Detach managed policies
            for pol in iam.list_attached_role_policies(RoleName=role["RoleName"])["AttachedPolicies"]:
                iam.detach_role_policy(RoleName=role["RoleName"], PolicyArn=pol["PolicyArn"])
            # Delete role
            iam.delete_role(RoleName=role["RoleName"])
            print(f"Deleted IAM role: {role['RoleName']}")
        except ClientError as e:
            print(f"Failed to delete IAM role {role['RoleName']}: {e}")

# -----------------------------
# 3. SNS topics and subscriptions
# -----------------------------
print("\nDeleting SNS topics and subscriptions...")
for topic in sns.list_topics()["Topics"]:
    arn = topic["TopicArn"]
    try:
        # Get all subscriptions for this topic
        subs = sns.list_subscriptions_by_topic(TopicArn=arn)["Subscriptions"]
        for sub in subs:
            sns.unsubscribe(SubscriptionArn=sub["SubscriptionArn"])
            print(f"Unsubscribed {sub['Endpoint']} from {arn}")

        # Delete the topic itself
        sns.delete_topic(TopicArn=arn)
        print(f"Deleted SNS topic: {arn}")
    except ClientError as e:
        print(f"Failed to delete SNS topic {arn}: {e}")

# -----------------------------
# 4. S3 buckets
# -----------------------------
print("\nDeleting S3 buckets...")
for bucket in s3.list_buckets()["Buckets"]:
    created = bucket["CreationDate"]
    if created >= cutoff:
        try:
            # Delete all objects
            objs = s3.list_objects_v2(Bucket=bucket["Name"]).get("Contents", [])
            for obj in objs:
                s3.delete_object(Bucket=bucket["Name"], Key=obj["Key"])
            # Delete bucket
            s3.delete_bucket(Bucket=bucket["Name"])
            print(f"Deleted S3 bucket: {bucket['Name']}")
        except ClientError as e:
            print(f"Failed to delete bucket {bucket['Name']}: {e}")

print("\nCleanup completed! All resources created in the last 24 hours have been deleted, including SNS subscriptions.")
