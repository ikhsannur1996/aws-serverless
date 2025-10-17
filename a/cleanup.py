import boto3, time

REGION = "us-east-1"
BASE_NAME = "image-compression"

# AWS clients
s3 = boto3.client("s3", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)
iam = boto3.client("iam")
sns = boto3.client("sns")
sts = boto3.client("sts")

ACCOUNT_ID = sts.get_caller_identity()["Account"]

# Prompt for the deployment timestamp
timestamp = input("Enter the timestamp of the deployment to clean up (e.g., 1697501234): ").strip()

# Resource names
SOURCE_BUCKET = f"{BASE_NAME}-source-{timestamp}"
TARGET_BUCKET = f"{BASE_NAME}-target-{timestamp}"
SNS_TOPIC_NAME = f"{BASE_NAME}-topic-{timestamp}"
LAMBDA_NAME = f"{BASE_NAME}-lambda-{timestamp}"
ROLE_NAME = f"{BASE_NAME}-role-{timestamp}"
POLICY_NAME = f"{BASE_NAME}-policy"
LAYER_NAME = f"{BASE_NAME}-pillow-layer-{timestamp}"

# -----------------------------
# 1. Delete S3 buckets
# -----------------------------
for bucket in [SOURCE_BUCKET, TARGET_BUCKET]:
    try:
        print(f"Deleting all objects in {bucket}...")
        objects = s3.list_objects_v2(Bucket=bucket)
        if "Contents" in objects:
            for obj in objects["Contents"]:
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
        s3.delete_bucket(Bucket=bucket)
        print(f"Deleted bucket: {bucket}")
    except Exception as e:
        print(f"Error deleting bucket {bucket}: {e}")

# -----------------------------
# 2. Delete Lambda function
# -----------------------------
try:
    lambda_client.delete_function(FunctionName=LAMBDA_NAME)
    print(f"Deleted Lambda function: {LAMBDA_NAME}")
except Exception as e:
    print(f"Error deleting Lambda function: {e}")

# -----------------------------
# 3. Delete Lambda Layer
# -----------------------------
try:
    versions = lambda_client.list_layer_versions(LayerName=LAYER_NAME).get("LayerVersions", [])
    for v in versions:
        lambda_client.delete_layer_version(LayerName=LAYER_NAME, VersionNumber=v["Version"])
    print(f"Deleted Lambda layer: {LAYER_NAME}")
except Exception as e:
    print(f"Error deleting Lambda layer: {e}")

# -----------------------------
# 4. Delete IAM inline policy
# -----------------------------
try:
    iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=POLICY_NAME)
    print(f"Deleted inline policy: {POLICY_NAME}")
except Exception as e:
    print(f"Error deleting IAM inline policy: {e}")

# -----------------------------
# 5. Detach and delete IAM role
# -----------------------------
try:
    iam.detach_role_policy(RoleName=ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
    iam.delete_role(RoleName=ROLE_NAME)
    print(f"Deleted IAM role: {ROLE_NAME}")
except Exception as e:
    print(f"Error deleting IAM role: {e}")

# -----------------------------
# 6. Delete SNS topic
# -----------------------------
try:
    topic_arn = f"arn:aws:sns:{REGION}:{ACCOUNT_ID}:{SNS_TOPIC_NAME}"
    sns.delete_topic(TopicArn=topic_arn)
    print(f"Deleted SNS topic: {SNS_TOPIC_NAME}")
except Exception as e:
    print(f"Error deleting SNS topic: {e}")

print("\nCleanup complete!")
