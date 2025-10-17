import boto3, os, time, json, shutil, subprocess, sys

REGION = "us-east-1"
BASE_NAME = "image-compression"

# -----------------------------
# Initialize AWS clients
# -----------------------------
print("Step 0: Initializing AWS clients...")
s3_client = boto3.client("s3", region_name=REGION)
iam_client = boto3.client("iam")
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
sts_client = boto3.client("sts")

ACCOUNT_ID = sts_client.get_caller_identity()["Account"]
print(f"Account ID: {ACCOUNT_ID}\n")

# -----------------------------
# Prompt for SNS emails
# -----------------------------
emails = input("Enter comma-separated SNS email addresses: ").split(",")

# -----------------------------
# Generate unique resource names
# -----------------------------
timestamp = int(time.time())
source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"
layer_name = f"{BASE_NAME}-opencv-layer-{timestamp}"

print(f"Resources will be created with timestamp: {timestamp}")

# -----------------------------
# Create S3 buckets
# -----------------------------
print("Creating S3 buckets...")
for bucket in [source_bucket, target_bucket]:
    if REGION == "us-east-1":
        s3_client.create_bucket(Bucket=bucket)
    else:
        s3_client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
    print(f"Bucket created: {bucket}")

# -----------------------------
# Create SNS topic and subscribe emails
# -----------------------------
sns_topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
for email in emails:
    email = email.strip()
    if email:
        sns_client.subscribe(TopicArn=sns_topic_arn, Protocol="email", Endpoint=email)
        print(f"Subscribed {email} to SNS topic")
print(f"SNS Topic ARN: {sns_topic_arn}\n")

# -----------------------------
# Create IAM role for Lambda
# -----------------------------
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
role = iam_client.create_role(RoleName=lambda_role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
print(f"IAM role {lambda_role_name} created, waiting 10s for propagation...")
time.sleep(10)

# Attach basic Lambda execution policy
iam_client.attach_role_policy(RoleName=lambda_role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")

# Attach inline policy for S3 and SNS
inline_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow",
         "Action": ["s3:GetObject","s3:PutObject"],
         "Resource":[f"arn:aws:s3:::{source_bucket}/*", f"arn:aws:s3:::{target_bucket}/*"]},
        {"Effect": "Allow",
         "Action":["sns:Publish"],
         "Resource":[sns_topic_arn]}
    ]
}
iam_client.put_role_policy(RoleName=lambda_role_name, PolicyName=f"{BASE_NAME}-policy", PolicyDocument=json.dumps(inline_policy))
print(f"Inline policy attached to {lambda_role_name}\n")

# -----------------------------
# Create Lambda layer for OpenCV
# -----------------------------
print("Creating Lambda layer with OpenCV headless...")
layer_dir = "layer_temp/python"
if os.path.exists("layer_temp"):
    shutil.rmtree("layer_temp")
os.makedirs(layer_dir)

# Install dependencies
subprocess.check_call([sys.executable, "-m", "pip", "install", "opencv-python-headless", "numpy", "-t", layer_dir])

# Create zip for layer
shutil.make_archive("opencv_layer", 'zip', "layer_temp")
with open("opencv_layer.zip", "rb") as f:
    layer_bytes = f.read()

layer_response = lambda_client.publish_layer_version(
    LayerName=layer_name,
    Content={"ZipFile": layer_bytes},  # <-- fixed
    CompatibleRuntimes=["python3.11"]
)
layer_arn = layer_response["LayerVersionArn"]
shutil.rmtree("layer_temp")
os.remove("opencv_layer.zip")
print(f"Lambda layer created: {layer_arn}\n")

# -----------------------------
# Package Lambda function
# -----------------------------
package_dir = "package_temp"
if os.path.exists(package_dir):
    shutil.rmtree(package_dir)
os.makedirs(package_dir)

shutil.copy("lambda_function.py", package_dir)
shutil.make_archive("lambda_package", 'zip', package_dir)
with open("lambda_package.zip", "rb") as f:
    zip_bytes = f.read()
shutil.rmtree(package_dir)
os.remove("lambda_package.zip")

# -----------------------------
# Create Lambda function
# -----------------------------
lambda_response = lambda_client.create_function(
    FunctionName=lambda_name,
    Runtime="python3.11",
    Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{lambda_role_name}",
    Handler="lambda_function.lambda_handler",
    Code={"ZipFile": zip_bytes},
    Layers=[layer_arn],
    Environment={"Variables":{"TARGET_BUCKET":target_bucket,"SNS_TOPIC_ARN":sns_topic_arn}},
)
lambda_arn = lambda_response["FunctionArn"]
print(f"Lambda function created: {lambda_arn}\n")

# -----------------------------
# Add S3 trigger to Lambda
# -----------------------------
print("Adding S3 trigger to Lambda function...")
lambda_client.add_permission(
    FunctionName=lambda_name,
    StatementId=f"s3-invoke-{timestamp}",
    Action="lambda:InvokeFunction",
    Principal="s3.amazonaws.com",
    SourceArn=f"arn:aws:s3:::{source_bucket}"
)

s3_client.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration={"LambdaFunctionConfigurations":[{"LambdaFunctionArn":lambda_arn,"Events":["s3:ObjectCreated:Put"]}]}
)
print("S3 trigger configured successfully.\n")

# -----------------------------
# Deployment complete
# -----------------------------
print("=== DEPLOYMENT COMPLETE ===")
print(f"Source Bucket: {source_bucket}")
print(f"Target Bucket: {target_bucket}")
print(f"SNS Topic ARN: {sns_topic_arn}")
print(f"Lambda Function ARN: {lambda_arn}")
print(f"Lambda Layer ARN: {layer_arn}")
print("Please confirm your SNS subscriptions via email!")
