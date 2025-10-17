import boto3
import json
import io
import csv
import PyPDF2
import os
import re
import collections
from datetime import datetime
from langdetect import detect, DetectorFactory
import uuid

s3 = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')

DetectorFactory.seed = 0

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
REPORT_TOPIC_ARN = os.environ['REPORT_TOPIC_ARN']

def extract_text(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    content = obj['Body'].read()

    if key.lower().endswith('.pdf'):
        pdf = PyPDF2.PdfReader(io.BytesIO(content))
        text = " ".join([page.extract_text() or "" for page in pdf.pages])
    elif key.lower().endswith('.csv'):
        lines = content.decode('utf-8', errors='ignore').splitlines()
        reader = csv.reader(lines)
        text = " ".join([" ".join(row) for row in reader])
    else:
        text = content.decode('utf-8', errors='ignore')

    return text.strip()

def analyze_text(text):
    words = re.findall(r'\b\w+\b', text.lower())
    word_freq = collections.Counter(words)
    top_words = word_freq.most_common(10)
    language = "unknown"
    try:
        language = detect(text)
    except Exception:
        pass
    return language, top_words

def lambda_handler(event, context):
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        text = extract_text(bucket, key)
        language, top_words = analyze_text(text)
        document_id = str(uuid.uuid4())

        table = dynamo.Table(DYNAMODB_TABLE)
        table.put_item(Item={
            'document_id': document_id,
            'file_name': key,
            'language': language,
            'top_words': json.dumps(top_words),
            'uploaded_at': datetime.utcnow().isoformat()
        })

        message = (
            f"✅ Document Processed: {key}\n"
            f"Language: {language}\n"
            f"Top 10 Words:\n" +
            "\n".join([f"{w}: {c}" for w, c in top_words])
        )

        sns.publish(
            TopicArn=REPORT_TOPIC_ARN,
            Subject=f"Document Analysis Report: {key}",
            Message=message
        )

    return {'status': 'success'}
