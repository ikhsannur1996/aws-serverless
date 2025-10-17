import boto3
import os
import io
import csv
import PyPDF2
import uuid
from langdetect import detect, DetectorFactory
from datetime import datetime

DetectorFactory.seed = 0

s3 = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
TOPIC_ARN = os.environ['TOPIC_ARN']

def extract_text(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    data = obj['Body'].read()
    text = ""

    if key.lower().endswith('.pdf'):
        reader = PyPDF2.PdfReader(io.BytesIO(data))
        text = " ".join([page.extract_text() or "" for page in reader.pages])
    elif key.lower().endswith('.csv'):
        csv_io = io.StringIO(data.decode('utf-8', errors='ignore'))
        reader = csv.reader(csv_io)
        text = " ".join([" ".join(row) for row in reader])
    elif key.lower().endswith('.txt'):
        text = data.decode('utf-8', errors='ignore')

    return text.strip()

def analyze_text(text):
    try:
        lang = detect(text) if text else "unknown"
    except Exception:
        lang = "unknown"
    word_count = len(text.split())
    return lang, word_count

def lambda_handler(event, context):
    for record in event.get('Records', []):
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        text = extract_text(bucket, key)
        lang, word_count = analyze_text(text)

        table = dynamo.Table(DYNAMODB_TABLE)
        document_id = str(uuid.uuid4())
        table.put_item(Item={
            'document_id': document_id,
            'file_name': key,
            'language': lang,
            'word_count': word_count,
            'uploaded_at': datetime.utcnow().isoformat()
        })

        message = (
            f"📄 Document Processed Successfully\n"
            f"File: {key}\n"
            f"Language: {lang}\n"
            f"Word Count: {word_count}\n"
            f"Upload Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )

        sns.publish(
            TopicArn=TOPIC_ARN,
            Subject=f"Document Processed: {key}",
            Message=message
        )

    return {"status": "success"}
