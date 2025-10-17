import boto3
from io import BytesIO
from PIL import Image
import os

TARGET_BUCKET = os.environ['TARGET_BUCKET']
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']

s3 = boto3.client("s3")
sns = boto3.client("sns")

def lambda_handler(event, context):
    summary_lines = []

    for record in event.get("Records", []):
        source_bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        try:
            response = s3.get_object(Bucket=source_bucket, Key=key)
            img_data = response['Body'].read()
            img = Image.open(BytesIO(img_data))
            buffer = BytesIO()

            if img.format == "JPEG":
                img.save(buffer, "JPEG", quality=60, optimize=True)
            elif img.format == "PNG":
                img.save(buffer, "PNG", optimize=True)
            else:
                img.save(buffer, img.format)

            buffer.seek(0)
            s3.put_object(Bucket=TARGET_BUCKET, Key=key, Body=buffer)
            summary_lines.append(f"{key}: compressed successfully")
            print(f"Compressed {key} and uploaded to {TARGET_BUCKET}")

        except Exception as e:
            summary_lines.append(f"{key}: error - {e}")
            print(f"Error processing {key}: {e}")

    if summary_lines:
        message = "\n".join(summary_lines)
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Image Compression Summary ({len(summary_lines)} file(s))",
            Message=message
        )

    return {"statusCode": 200, "body": "Images processed and notification sent."}
