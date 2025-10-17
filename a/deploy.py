import boto3, os, time, json, subprocess, shutil, sys

REGION = "us-east-1"
BASE_NAME = "image-compression"
EMAILS = ["youremail@example.com"]  # Add subscriber emails

# AWS clients
s3 = boto3.client("s3", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)
iam = boto3.client("iam")
sns = boto3.client("sns")
sts = boto3.client("sts")
ACCOUNT_ID = sts.get_caller_identity()["Account"]

timestamp = int(time.time())
SOURCE_BUCKET = f"{BASE_NAME}-source-{timestamp}"
TARGET_BUCKET = f"{BASE_NAME}-target-{timestamp}"
SNS_TOPIC_NAME = f"{BASE_NAME}-topic-{timestamp}"
LAMBDA_NAME = f"{BASE_NAME}-lambda-{timestamp}"
ROLE_NAME = f"{BASE_NAME}-role-{timestamp}"

print("Deploying Image Compression Lambda...\n")

# 1. Create S3 buckets
for bucket in [SOURCE_BUCKET, TARGET_BUCKET]:
    if REGION == "us-east-1":
        s3.create_bucket(Bucket=bucket)
    else:
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
    print(f"Bucket created: {bucket}")

# 2. Create SNS topic
sns_topic_arn = sns.create_topic(Name=SNS_TOPIC_NAME)["TopicArn"]
for email in EMAILS:
    sns.subscribe(TopicArn=sns_topic_arn, Protocol="email", Endpoint=email)
    print(f"Subscribed {email} to SNS topic")

# 3. Create IAM role
trust_policy = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}
role = iam.create_role(RoleName=ROLE_NAME, AssumeRolePolicyDocument=json.dumps(trust_policy))
time.sleep(10)
iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
inline_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject"],
            "Resource":[f"arn:aws:s3:::{SOURCE_BUCKET}/*", f"arn:aws:s3:::{TARGET_BUCKET}/*"]
        },
        {
            "Effect": "Allow",
            "Action": ["sns:Publish"],
            "Resource": [sns_topic_arn]
        }
    ]
}
iam.put_role_policy(RoleName=ROLE_NAME, PolicyName=f"{BASE_NAME}-policy", PolicyDocument=json.dumps(inline_policy))

# 4. Package Lambda with dependencies
package_dir = "package_temp"
if os.path.exists(package_dir):
    shutil.rmtree(package_dir)
os.makedirs(package_dir)

subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-t", package_dir])
shutil.copy("lambda_function.py", package_dir)
shutil.make_archive("lambda_package", 'zip', package_dir)
with open("lambda_package.zip", "rb") as f:
    zip_bytes = f.read()
shutil.rmtree(package_dir)

# 5. Create Lambda function
lambda_response = lambda_client.create_function(
    FunctionName=LAMBDA_NAME,
    Runtime="python3.11",
    Role=f"arn:aws:iam::{ACCOUNT_ID}:role/{ROLE_NAME}",
    Handler="lambda_function.lambda_handler",
    Code={"ZipFile": zip_bytes},
    Environment={"Variables":{"TARGET_BUCKET":TARGET_BUCKET, "SNS_TOPIC_ARN":sns_topic_arn}}
)
lambda_arn = lambda_response["FunctionArn"]

# 6. Add S3 trigger
time.sleep(10)
lambda_client.add_permission(
    FunctionName=LAMBDA_NAME,
    StatementId=f"s3-invoke-{timestamp}",
    Action="lambda:InvokeFunction",
    Principal="s3.amazonaws.com",
    SourceArn=f"arn:aws:s3:::{SOURCE_BUCKET}"
)
notification_config = {"LambdaFunctionConfigurations":[{"LambdaFunctionArn":lambda_arn,"Events":["s3:ObjectCreated:Put"]}]}
s3.put_bucket_notification_configuration(Bucket=SOURCE_BUCKET, NotificationConfiguration=notification_config)

os.remove("lambda_package.zip")
print("\nDeployment complete!")
print(f"Source Bucket: {SOURCE_BUCKET}")
print(f"Target Bucket: {TARGET_BUCKET}")
print(f"SNS Topic ARN: {sns_topic_arn}")
print(f"Lambda ARN: {lambda_arn}")
print("Please confirm your SNS subscription emails.")
