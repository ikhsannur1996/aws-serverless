# S3 Image Compression with AWS Lambda and SNS Notifications

This project demonstrates a **serverless AWS application** using **SAM** that:

1. Compresses images uploaded to a **Source S3 Bucket**.
2. Saves compressed images to a **Target S3 Bucket**.
3. Sends **email notifications via SNS** with **detailed before/after image metadata** and **temporary pre-signed URLs** for public image preview.
4. Supports **single or multiple file uploads** per event.

---

## 🧱 Project Structure

```
s3-image-compress-batch/
├── template.yaml       # AWS SAM template
├── README.md           # Project documentation
├── requirements.txt    # Python dependencies
└── src/
    └── app.py          # Lambda function code
```

---

## ⚙ Requirements

### Local

* Python 3.12+
* AWS SAM CLI
* AWS CLI configured with credentials

### Python Dependencies (`requirements.txt`)

```txt
boto3
Pillow
```

Install dependencies locally (optional for testing or packaging):

```bash
pip install -r requirements.txt -t src/
```

---

## 🔧 Deployment Instructions

1. **Validate SAM template**

```bash
sam validate
```

2. **Build the SAM project**

```bash
sam build
```

3. **Deploy the SAM stack**

```bash
sam deploy --guided
```

* Provide a **stack name** (e.g., `image-compress-stack`)
* Accept default permissions
* SAM will automatically create:

  * **Source S3 bucket**
  * **Target S3 bucket**
  * **SNS topic**
  * **Lambda function**

4. **Subscribe your email to SNS topic**:

* Go to **AWS SNS Console → Topics → YourTopic → Create subscription**
* Protocol: `Email`
* Endpoint: your email address
* Confirm subscription in your inbox

---

## 📄 AWS SAM Template (`template.yaml`)

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Compress single or multiple images from S3 and send batch metadata email notifications with pre-signed URLs

Globals:
  Function:
    Timeout: 30
    Runtime: python3.12
    Environment:
      Variables:
        TARGET_BUCKET: !Sub "image-target-bucket-${AWS::AccountId}"

Resources:
  SourceBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub "image-source-bucket-${AWS::AccountId}"

  TargetBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub "image-target-bucket-${AWS::AccountId}"

  ImageNotificationTopic:
    Type: AWS::SNS::Topic
    Properties:
      DisplayName: Image Upload Notification

  ImageCompressLambda:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: image-compress-lambda
      Handler: app.lambda_handler
      CodeUri: src/
      Policies:
        - AWSLambdaBasicExecutionRole
        - S3ReadPolicy:
            BucketName: !Ref SourceBucket
        - S3WritePolicy:
            BucketName: !Ref TargetBucket
        - SNSPublishMessagePolicy:
            TopicName: !Ref ImageNotificationTopic
      Environment:
        Variables:
          TARGET_BUCKET: !Ref TargetBucket
          SNS_TOPIC_ARN: !Ref ImageNotificationTopic
      Events:
        S3UploadEvent:
          Type: S3
          Properties:
            Bucket: !Ref SourceBucket
            Events: s3:ObjectCreated:*

Outputs:
  SourceBucketName:
    Value: !Ref SourceBucket
  TargetBucketName:
    Value: !Ref TargetBucket
  SNSTopicArn:
    Value: !Ref ImageNotificationTopic
```

---

## 🐍 Lambda Function (`src/app.py`)

```python
import boto3
import os
from io import BytesIO
from PIL import Image

s3 = boto3.client("s3")
sns = boto3.client("sns")

TARGET_BUCKET = os.environ['TARGET_BUCKET']
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']

def compress_image(image_content):
    """Compress image and return buffer and metadata"""
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
    """Generate a pre-signed URL valid for 1 hour (3600 seconds)"""
    return s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=expiration
    )

def lambda_handler(event, context):
    summary_lines = []
    for record in event.get("Records", []):
        source_bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        # Download image
        response = s3.get_object(Bucket=source_bucket, Key=key)
        image_content = response['Body'].read()

        # Compress image and get metadata
        buffer, meta = compress_image(image_content)

        # Upload compressed image
        s3.put_object(Bucket=TARGET_BUCKET, Key=key, Body=buffer)

        # Generate pre-signed URL for download
        presigned_url = generate_presigned_url(TARGET_BUCKET, key)

        # Add to summary
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

    # Compose email
    subject = f"Images Compressed: {len(summary_lines)} file(s)"
    message = "\n\n".join(summary_lines)

    # Send SNS notification
    sns.publish(TopicArn=SNS_TOPIC_ARN, Message=message, Subject=subject)

    print(subject)
    print(message)

    return {"statusCode": 200, "body": "Images compressed and notification with preview links sent."}
```

---

## 🧪 Example Email Output (with 1-hour preview links)

```
photo1.jpg
------------------------------------------------------------
Original Format      : JPEG
Original Size        : 1450.34 KB
Original Dimensions  : 1920x1080
Compressed Format    : JPEG
Compressed Size      : 512.12 KB
Compressed Dimensions: 1920x1080
Preview Link         : https://<bucket>.s3.<region>.amazonaws.com/photo1.jpg?AWSAccessKeyId=...&Expires=...&Signature=...

photo2.png
------------------------------------------------------------
Original Format      : PNG
Original Size        : 120.25 KB
Original Dimensions  : 800x600
Compressed Format    : PNG
Compressed Size      : 95.75 KB
Compressed Dimensions: 800x600
Preview Link         : https://<bucket>.s3.<region>.amazonaws.com/photo2.png?AWSAccessKeyId=...&Expires=...&Signature=...
```

**Email Subject:**

```
Images Compressed: 2 file(s)
```

---

This README now contains:

* **Full SAM template**
* **Lambda Python code with 1-hour pre-signed URLs**
* **requirements.txt info**
* **Beautiful formatted email output**
* **Deployment instructions and project structure**
