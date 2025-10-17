import boto3
import os
from io import BytesIO
from PIL import Image

s3 = boto3.client("s3")
sns = boto3.client("sns")

TARGET_BUCKET = os.environ['TARGET_BUCKET']
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']

def compress_image(image_content):
    before_size_kb = len(image_content) / 1024
    img = Image.open(BytesIO(image_content))
    before_format = img.format
    before_width, before_height = img.size

    buffer = BytesIO()
    if img.format == 'JPEG':
        img.save(buffer, format='JPEG', quality=60, optimize=True)
    elif img.format == 'PNG':
        img.save(buffer, format='PNG', optimize=True)
    else:
        img.save(buffer, format=img.format)

    buffer.seek(0)
    after_size_kb = len(buffer.getvalue()) / 1024
    after_img = Image.open(buffer)
    after_format = after_img.format
    after_width, after_height = after_img.size

    return buffer, {
        "before_format": before_format,
        "before_width": before_width,
        "before_height": before_height,
        "before_size_kb": before_size_kb,
        "after_format": after_format,
        "after_width": after_width,
        "after_height": after_height,
        "after_size_kb": after_size_kb
    }

def generate_presigned_url(bucket, key, expiration=3600):
    return s3.generate_presigned_url('get_object', Params={'Bucket': bucket, 'Key': key}, ExpiresIn=expiration)

def lambda_handler(event, context):
    summary_lines = []

    for record in event.get("Records", []):
        source_bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        try:
            response = s3.get_object(Bucket=source_bucket, Key=key)
            image_content = response['Body'].read()

            buffer, meta = compress_image(image_content)
            s3.put_object(Bucket=TARGET_BUCKET, Key=key, Body=buffer)
            presigned_url = generate_presigned_url(TARGET_BUCKET, key)

            summary_lines.append(
                f"{key}\n"
                f"{'-'*60}\n"
                f"{'Original Format':<20}: {meta['before_format']}\n"
                f"{'Original Size':<20}: {meta['before_size_kb']:.2f} KB\n"
                f"{'Original Dimensions':<20}: {meta['before_width']}x{meta['before_height']}\n"
                f"{'Compressed Format':<20}: {meta['after_format']}\n"
                f"{'Compressed Size':<20}: {meta['after_size_kb']:.2f} KB\n"
                f"{'Compressed Dimensions':<20}: {meta['after_width']}x{meta['after_height']}\n"
                f"{'Preview Link':<20}: {presigned_url}\n"
            )
        except Exception as e:
            summary_lines.append(f"Error processing {key}: {str(e)}")

    subject = f"Images Compressed: {len(summary_lines)} file(s)"
    message = "\n\n".join(summary_lines)
    sns.publish(TopicArn=SNS_TOPIC_ARN, Message=message, Subject=subject)

    return {"statusCode": 200, "body": "Images compressed and notification sent."}
