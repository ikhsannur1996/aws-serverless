import boto3, zipfile, io, os, time, json, subprocess, shutil, sys

REGION = "us-east-1"
BASE_NAME = "image-compression"

print("Step 0: Initializing AWS clients...")
s3_client = boto3.client("s3", region_name=REGION)
iam_client = boto3.client("iam")
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
sts_client = boto3.client("sts")

ACCOUNT_ID = sts_client.get_caller_identity()["Account"]
print(f"Account ID: {ACCOUNT_ID}\n")

# -----------------------------
# 1. Prompt for SNS emails
# -----------------------------
print("Step 1: Enter comma-separated email addresses for SNS notifications:")
emails = input().split(",")

# -----------------------------
# 2. Generate unique resource names
# -----------------------------
timestamp = int(time.time())
source_bucket = f"{BASE_NAME}-source-{timestamp}"
target_bucket = f"{BASE_NAME}-target-{timestamp}"
sns_topic_name = f"{BASE_NAME}-topic-{timestamp}"
lambda_name = f"{BASE_NAME}-lambda-{timestamp}"
lambda_role_name = f"{BASE_NAME}-role-{timestamp}"
layer_name = f"{BASE_NAME}-opencv-layer-{timestamp}"

print("Step 2: Generated resource names:")
print(f"Source bucket: {source_bucket}")
print(f"Target bucket: {target_bucket}")
print(f"SNS topic: {sns_topic_name}")
print(f"Lambda function: {lambda_name}")
print(f"IAM role: {lambda_role_name}")
print(f"Lambda layer: {layer_name}\n")

# -----------------------------
# 3. Create S3 buckets
# -----------------------------
print("Step 3: Creating S3 buckets...")
for bucket in [source_bucket, target_bucket]:
    try:
        if REGION == "us-east-1":
            s3_client.create_bucket(Bucket=bucket)
        else:
            s3_client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
        print(f"Created bucket: {bucket}")
    except Exception as e:
        print(f"Error creating bucket {bucket}: {e}")

# -----------------------------
# 4. Create SNS topic and subscribe emails
# -----------------------------
print("\nStep 4: Creating SNS topic and subscribing emails...")
sns_topic_arn = sns_client.create_topic(Name=sns_topic_name)["TopicArn"]
for email in emails:
    email = email.strip()
    if email:
        sns_client.subscribe(TopicArn=sns_topic_arn, Protocol="email", Endpoint=email)
        print(f"Subscribed {email} to SNS topic")

# -----------------------------
# 5. Create IAM role for Lambda
# -----------------------------
print("\nStep 5: Creating IAM role for Lambda...")
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
role = iam_client.create_role(RoleName=lambda_role_name, AssumeRolePolicyDocument=json.dumps(trust_policy))
print("IAM role created, waiting 10 seconds for propagation...")
time.sleep(10)

iam_client.attach_role_policy(RoleName=lambda_role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
print("Attached AWSLambdaBasicExecutionRole policy.")

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
print("Attached inline policy for S3 and SNS.\n")

# -----------------------------
# 6. Create OpenCV Lambda Layer
# -----------------------------
print("Step 6: Creating OpenCV Lambda Layer...")
layer_dir = "layer_temp/python"
if os.path.exists("layer_temp"):
    shutil.rmtree("layer_temp")
os.makedirs(layer_dir)

# Install OpenCV headless + numpy
subprocess.check_call([sys.executable, "-m", "pip", "install", "opencv-python-headless", "numpy", "-t", layer_dir])

# Zip the layer
shutil.make_archive("opencv_layer", 'zip', "layer_temp")
with open("opencv_layer.zip", 'rb') as f:
    layer_bytes = f.read()

layer_response = lambda_client.publish_layer_version(
    LayerName=layer_name,
    ZipFile=layer_bytes,
    CompatibleRuntimes=["python3.11"],
)
layer_arn = layer_response["LayerVersionArn"]
print(f"OpenCV Lambda layer created: {layer_arn}")

# Cleanup layer temp files
shutil.rmtree("layer_temp")
os.remove("opencv_layer.zip")

# -----------------------------
# 7. Prepare Lambda function package
# -----------------------------
print("\nStep 7: Preparing Lambda function package...")
package_dir = "package_temp"
if os.path.exists(package_dir):
    shutil.rmtree(package_dir)
os.makedirs(package_dir)

# Copy lambda_function.py (OpenCV version) into package_dir
shutil.copy("lambda_function.py", package_dir)

zip_path = "lambda_package.zip"
shutil.make_archive("lambda_package", 'zip', package_dir)
with open(zip_path, 'rb') as f:
    zip_bytes = f.read()

# -----------------------------
# 8. Create Lambda function
# -----------------------------
print("Step 8: Deploying Lambda function...")
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
print(f"Lambda function {lambda_name} created: {lambda_arn}\n")

# Cleanup package temp
shutil.rmtree(package_dir)
os.remove(zip_path)

# -----------------------------
# 9. Add permission for S3 to invoke Lambda
# -----------------------------
print("Step 9: Adding S3 invoke permission to Lambda...")
time.sleep(10)
lambda_client.add_permission(
    FunctionName=lambda_name,
    StatementId=f"s3-invoke-{timestamp}",
    Action="lambda:InvokeFunction",
    Principal="s3.amazonaws.com",
    SourceArn=f"arn:aws:s3:::{source_bucket}"
)
time.sleep(5)

# -----------------------------
# 10. Add S3 trigger
# -----------------------------
print("Step 10: Configuring S3 bucket trigger to Lambda...")
notification_configuration = {
    "LambdaFunctionConfigurations":[{"LambdaFunctionArn":lambda_arn,"Events":["s3:ObjectCreated:Put"]}]
}
s3_client.put_bucket_notification_configuration(
    Bucket=source_bucket,
    NotificationConfiguration=notification_configuration
)

# -----------------------------
# 11. Deployment complete
# -----------------------------
print("\nDeployment Complete!")
print(f"Source Bucket: {source_bucket}")
print(f"Target Bucket: {target_bucket}")
print(f"SNS Topic ARN: {sns_topic_arn}")
print(f"Lambda Function ARN: {lambda_arn}")
print(f"Lambda Layer ARN: {layer_arn}")
print("Please confirm your SNS subscriptions via email!")
