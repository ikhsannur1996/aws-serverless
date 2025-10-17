import boto3
import os

sns = boto3.client('sns')
TOPIC_ARN = os.environ['TOPIC_ARN']

def lambda_handler(event, context):
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        message = (
            f"📤 File Uploaded to S3\n"
            f"Bucket: {bucket}\n"
            f"Key: {key}\n\n"
            f"The document will now be extracted and analyzed automatically."
        )

        sns.publish(
            TopicArn=TOPIC_ARN,
            Subject="📄 New File Uploaded to S3",
            Message=message
        )

    return {"status": "upload_notification_sent"}
