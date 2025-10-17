import boto3
import os

sns = boto3.client('sns')
TOPIC_ARN = os.environ['TOPIC_ARN']

def lambda_handler(event, context):
    try:
        record = event['Records'][0]
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        event_time = record['eventTime']
    except Exception as e:
        print("Error parsing event:", e)
        return {"status": "error", "message": str(e)}

    message = (
        f"📂 New file uploaded!\n"
        f"Bucket: {bucket}\n"
        f"File: {key}\n"
        f"Upload time: {event_time}\n\n"
        f"The system will now extract and analyze this file automatically."
    )

    sns.publish(
       
