import boto3
import re
import collections
from langdetect import detect, DetectorFactory
import os
from datetime import datetime
import logging

# For consistent language detection results
DetectorFactory.seed = 0

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
TOPIC_ARN = os.environ['TOPIC_ARN']

def perform_analysis(items):
    # Concatenate all texts from DynamoDB items
    full_text = " ".join(item.get('text', '') for item in items)

    # Detect dominant language of the entire text corpus
    try:
        language = detect(full_text) if full_text.strip() else 'unknown'
    except Exception:
        language = "unknown"

    # Tokenize and count word frequency (case-insensitive, words only)
    words = re.findall(r'\b\w+\b', full_text.lower())
    word_freq = collections.Counter(words)

    # Extract top 10 most frequent words (skip extremely common stopwords could be a future improvement)
    top_words = word_freq.most_common(10)
    top_words_str = "\n".join(f"{word}: {count}" for word, count in top_words)

    message = (
        f"Document Analytics Report\n"
        f"Analysis Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Total Documents Analyzed: {len(items)}\n"
        f"Detected Language: {language}\n"
        f"Top 10 Word Frequencies:\n{top_words_str}\n"
    )
    return message

def lambda_handler(event, context):
    logger.info(f"Analyzer received event: {event}")

    table = dynamo.Table(DYNAMODB_TABLE)

    # If a document_id is provided, analyze only that document plus optionally others.
    document_id = None
    if isinstance(event, dict):
        document_id = event.get('document_id')

    try:
        if document_id:
            # Fetch only the provided document
            response = table.get_item(Key={'document_id': document_id})
            item = response.get('Item')
            items = [item] if item else []
        else:
            # Scan full table (careful with large tables; for production use pagination)
            response = table.scan()
            items = response.get('Items', [])
    except Exception as e:
        logger.exception(f"Failed to read from DynamoDB: {e}")
        return {'status': 'error', 'message': 'Failed to read from DynamoDB'}

    report_message = perform_analysis(items)

    try:
        sns.publish(
            TopicArn=TOPIC_ARN,
            Subject="📊 Document Analytics Report",
            Message=report_message
        )
    except Exception as e:
        logger.exception(f"Failed to publish SNS message: {e}")
        return {'status': 'error', 'message': 'Failed to publish SNS message'}

    return {'status': 'report_sent', 'total_docs': len(items)}
