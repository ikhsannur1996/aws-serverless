import boto3
import time

REGION = "us-east-1"
BASE_NAME = "image-compression"

# AWS clients
s3_client = boto3.client("s3", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)
sns_client = boto3.client("sns")
iam_client = boto3.client("iam")
sts_client = boto3.client("sts")

ACCOUNT_ID = sts_client.get_caller_identity()["Account"]

# -----------------------------
# 1. Prompt for deployment timestamp
# -----------------------------
print("Step 1: Enter the deployment timestamp to clean up resources.")
timestamp = input("Deployment timestamp: ").strip()

source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"

print("\nStarting cleanup process...\n")

# -----------------------------
# 2. Delete Lambda function
# -----------------------------
print("Step 2: Deleting Lambda function...")
try:
    lambda_client.delete_function(FunctionName=lambda_name)
    print(f"Lambda function {lambda_name} deleted.")
except Exception as e:
    print(f"Lambda deletion skipped: {e}")
print("")

# -----------------------------
# 3. Delete S3 buckets (with objects)
# -----------------------------
for idx, bucket in enumerate([source_bucket, target_bucket], start=3):
    print(f"Step {idx}: Deleting bucket {bucket} and all objects...")
    try:
        # Delete all objects
        response = s3_client.list_objects_v2(Bucket=bucket)
        if 'Contents' in response:
            for obj in response['Contents']:
                s3_client.delete_object(Bucket=bucket, Key=obj['Key'])
                print(f"Deleted object {obj['Key']} from {bucket}")
        # Delete the bucket
        s3_client.delete_bucket(Bucket=bucket)
        print(f"Bucket {bucket} deleted.")
    except Exception as e:
        print(f"Bucket deletion skipped ({bucket}): {e}")
    print("")

# -----------------------------
# 4. Delete SNS topic
# -----------------------------
print(f"Step 5: Deleting SNS topic {sns_topic_name}...")
try:
    topic_arn = f"arn:aws:sns:{REGION}:{ACCOUNT_ID}:{sns_topic_name}"
    sns_client.delete_topic(TopicArn=topic_arn)
    print(f"SNS topic {sns_topic_name} deleted.")
except Exception as e:
    print(f"SNS deletion skipped: {e}")
print("")

# -----------------------------
# 5. Delete IAM role
# -----------------------------
print(f"Step 6: Deleting IAM role {lambda_role_name}...")
try:
    # Detach managed policy
    iam_client.detach_role_policy(RoleName=lambda_role_name,
                                  PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
    print("Detached AWSLambdaBasicExecutionRole policy.")

    # Delete inline policies
    inline_policies = iam_client.list_role_policies(RoleName=lambda_role_name)['PolicyNames']
    for policy in inline_policies:
        iam_client.delete_role_policy(RoleName=lambda_role_name, PolicyName=policy)
        print(f"Deleted inline policy {policy}")

    # Delete the role
    iam_client.delete_role(RoleName=lambda_role_name)
    print(f"IAM role {lambda_role_name} deleted.")
except Exception as e:
    print(f"IAM role deletion skipped: {e}")
print("")

# -----------------------------
# Cleanup complete
# -----------------------------
print("Step 7: Cleanup complete! All specified resources have been removed (if they existed).")
