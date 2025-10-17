import boto3
import re
import collections
from langdetect import detect, DetectorFactory
import os
from datetime import datetime

# For consistent language detection results
DetectorFactory.seed = 0

dynamo = boto3.resource('dynamodb')
sns = boto3.client('sns')

DYNAMODB_TABLE = os.environ['DYNAMODB_TABLE']
TOPIC_ARN = os.environ['TOPIC_ARN']

def perform_analysis(items):
    # Concatenate all texts from DynamoDB items
    full_text = " ".join(item['text'] for item in items if 'text' in item)
    
    # Detect dominant language of the entire text corpus
    try:
        language = detect(full_text)
    except Exception:
        language = "unknown"
    
    # Tokenize and count word frequency (case-insensitive, words only)
    words = re.findall(r'\b\w+\b', full_text.lower())
    word_freq = collections.Counter(words)
    
    # Extract top 10 most frequent words
    top_words = word_freq.most_common(10)
    top_words_str = "\n".join(f"{word}: {count}" for word, count in top_words)
    
    message = (
        f"Document Analytics Report\n"
        f"Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Total Documents Analyzed: {len(items)}\n"
        f"Detected Language: {language}\n"
        f"Top 10 Word Frequencies:\n{top_words_str}\n"
    )
    return message

def lambda_handler(event, context):
    table = dynamo.Table(DYNAMODB_TABLE)
    response = table.scan()
    items = response.get('Items', [])
    
    report_message = perform_analysis(items)
    
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="Document Analytics Report",
        Message=report_message
    )
    
    return {'status': 'report_sent', 'total_docs': len(items)}
