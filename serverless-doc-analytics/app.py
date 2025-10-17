import boto3
import json
import io
import csv
import PyPDF2
import re
import collections
from langdetect import detect, DetectorFactory
import os
import uuid
from datetime import datetime

# Initialize AWS clients
s3 = boto3.client('s3')
dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')

# Environment variables
DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
TOPIC_ARN = os.environ['TOPIC_ARN']

DetectorFactory.seed = 0  # consistent language detection

def extract_text(bucket, key):
    """Extract text from supported file types."""
    obj = s3.get_object(Bucket=bucket, Key=key)
    content_bytes = obj['Body'].read()
    text = ""

    if key.lower().endswith('.pdf'):
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(content_bytes))
        text = " ".join([page.extract_text() or "" for page in pdf_reader.pages])
    elif key.lower().endswith('.txt'):
        text = content_bytes.decode('utf-8', errors='ignore')
    elif key.lower().endswith('.csv'):
        csv_str = content_bytes.decode('utf-8', errors='ignore')
        reader = csv.reader(io.StringIO(csv_str))
        text = " ".join(" ".join(row) for row in reader)
    else:
        text = "(Unsupported file type)"
    return text


def analyze_text(full_text):
    """Perform simple analytics: language + word frequency."""
    try:
        language = detect(full_text)
    except Exception:
        language = "unknown"

    words = re.findall(r'\b\w+\b', full_text.lower())
    word_freq = collections.Counter(words)
    top_words = word_freq.most_common(10)
    summary = "\n".join([f"{w}: {c}" for w, c in top_words])
    return language, summary


def lambda_handler(event, context):
    print("Event received:", json.dumps(event))

    try:
        record = event['Records'][0]
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
    except (KeyError, IndexError) as e:
        print("Invalid event structure:", e)
        return {"status": "error", "reason": "Invalid event structure"}

    # Step 1: Extract text
    text = extract_text(bucket, key)
    print(f"Extracted text length: {len(text)}")

    # Step 2: Analyze text
    language, top_words_summary = analyze_text(text)

    # Step 3: Save to DynamoDB
    doc_id = str(uuid.uuid4())
    table = dynamo.Table(DYNAMODB_TABLE)
    table.put_item(
        Item={
            'document_id': doc_id,
            'file_name': key,
            'language': language,
            'text': text[:1000],  # store first 1000 chars to avoid large payloads
            'created_at': datetime.now().isoformat()
        }
    )

    # Step 4: Send SNS notification
    message = (
        f"📄 Document Analytics Report\n"
        f"File: {key}\n"
        f"Language Detected: {language}\n"
        f"Top 10 Words:\n{top_words_summary}\n"
        f"Document ID: {doc_id}\n"
        f"Uploaded at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject=f"Document Processed: {os.path.basename(key)}",
        Message=message
    )

    print("SNS notification sent successfully.")
    return {"status": "success", "file": key, "document_id": doc_id}
