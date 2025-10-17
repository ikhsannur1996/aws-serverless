import boto3
import os
import io
import uuid
from datetime import datetime
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0

s3 = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
TOPIC_ARN = os.environ['TOPIC_ARN']

def lambda_handler(event, context):
    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        # Read file from S3
        obj = s3.get_object(Bucket=bucket, Key=key)
        text = obj['Body'].read().decode('utf-8', errors='ignore')

        # Analyze
        try:
            language = detect(text)
        except Exception:
            language = "unknown"
        word_count = len(text.split())

        # Save to DynamoDB
        table = dynamo.Table(DYNAMODB_TABLE)
        document_id = str(uuid.uuid4())
        table.put_item(Item={
            'document_id': document_id,
            'file_name': key,
            'language': language,
            'word_count': word_count,
            'uploaded_at': datetime.utcnow().isoformat()
        })

        # Send SNS notification
        message = (
            f"✅ Text Document Processed\n"
            f"File: {key}\n"
            f"Language: {language}\n"
            f"Word Count: {word_count}\n"
            f"Upload Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        sns.publish(
            TopicArn=TOPIC_ARN,
            Subject=f"Document Processed: {key}",
            Message=message
        )

    return {"status": "success"}
