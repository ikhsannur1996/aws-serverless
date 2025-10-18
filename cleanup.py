import boto3
from datetime import datetime, timezone, timedelta

REGION = "us-east-1"
BASE_NAME = "word-analysis"

s3_client = boto3.client("s3", region_name=REGION)
sns_client = boto3.client("sns")
lambda_client = boto3.client("lambda", region_name=REGION)
iam_client = boto3.client("iam")
dynamodb_client = boto3.client("dynamodb")
sts_client = boto3.client("sts")
account_id = sts_client.get_caller_identity()["Account"]

cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

# -----------------------------
# 1. Delete Lambda functions created in last 24h
# -----------------------------
print("Checking Lambda functions...")
for fn in lambda_client.list_functions()['Functions']:
    created = fn['LastModified']
    fn_name = fn['FunctionName']
    created_dt = datetime.strptime(created, "%Y-%m-%dT%H:%M:%S.%f%z")
    if created_dt >= cutoff and BASE_NAME in fn_name:
        print(f"Deleting Lambda: {fn_name}")
        lambda_client.delete_function(FunctionName=fn_name)

# -----------------------------
# 2. Delete IAM roles created in last 24h
# -----------------------------
print("Checking IAM roles...")
for role in iam_client.list_roles()['Roles']:
    role_name = role['RoleName']
    created = role['CreateDate']
    if created >= cutoff and BASE_NAME in role_name:
        print(f"Deleting IAM role: {role_name}")
        # Delete inline policies
        for pol in iam_client.list_role_policies(RoleName=role_name)['PolicyNames']:
            iam_client.delete_role_policy(RoleName=role_name, PolicyName=pol)
        # Detach managed policies
        for pol in iam_client.list_attached_role_policies(RoleName=role_name)['AttachedPolicies']:
            iam_client.detach_role_policy(RoleName=role_name, PolicyArn=pol['PolicyArn'])
        # Delete role
        iam_client.delete_role(RoleName=role_name)

# -----------------------------
# 3. Delete S3 buckets created in last 24h
# -----------------------------
print("Checking S3 buckets...")
for bucket in s3_client.list_buckets()['Buckets']:
    bucket_name = bucket['Name']
    created = bucket['CreationDate']
    if created >= cutoff and BASE_NAME in bucket_name:
        print(f"Deleting S3 bucket: {bucket_name}")
        # Delete objects (including versioned)
        try:
            paginator = s3_client.get_paginator('list_object_versions')
            for page in paginator.paginate(Bucket=bucket_name):
                versions = page.get('Versions', []) + page.get('DeleteMarkers', [])
                for v in versions:
                    s3_client.delete_object(Bucket=bucket_name, Key=v['Key'], VersionId=v['VersionId'])
        except s3_client.exceptions.NoSuchBucket:
            pass
        # Delete bucket
        s3_client.delete_bucket(Bucket=bucket_name)

# -----------------------------
# 4. Delete SNS topics created in last 24h
# -----------------------------
print("Checking SNS topics...")
for topic in sns_client.list_topics()['Topics']:
    arn = topic['TopicArn']
    if BASE_NAME in arn:
        print(f"Deleting SNS topic: {arn}")
        # Unsubscribe all confirmed subscriptions
        subs = sns_client.list_subscriptions_by_topic(TopicArn=arn)['Subscriptions']
        for sub in subs:
            sub_arn = sub.get('SubscriptionArn')
            if sub_arn and sub_arn != 'PendingConfirmation':
                try:
                    sns_client.unsubscribe(SubscriptionArn=sub_arn)
                    print(f"Unsubscribed {sub_arn}")
                except Exception as e:
                    print(f"Failed to unsubscribe {sub_arn}: {e}")
        # Delete topic
        try:
            sns_client.delete_topic(TopicArn=arn)
            print(f"Deleted SNS topic {arn}")
        except Exception as e:
            print(f"Failed to delete topic {arn}: {e}")

# -----------------------------
# 5. Delete DynamoDB tables created in last 24h
# -----------------------------
print("Checking DynamoDB tables...")
for table_name in dynamodb_client.list_tables()['TableNames']:
    if BASE_NAME in table_name:
        desc = dynamodb_client.describe_table(TableName=table_name)['Table']
        created = desc['CreationDateTime']
        if created >= cutoff:
            print(f"Deleting DynamoDB table: {table_name}")
            dynamodb_client.delete_table(TableName=table_name)
            waiter = dynamodb_client.get_waiter('table_not_exists')
            waiter.wait(TableName=table_name)

print("\nCLEANUP COMPLETE: All resources created in last 24 hours have been removed.")
