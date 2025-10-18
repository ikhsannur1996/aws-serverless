# Simple Word Analysis Serverless App

This project demonstrates a **serverless AWS application** to perform **basic word analysis** on text files uploaded to S3. The app automatically stores word counts in **DynamoDB** and sends a **summary via SNS email**. All resources are created via a **single deploy script** and can be removed with a **cleanup script**.

---

## Features

* **Serverless architecture** using AWS Lambda.
* Detects **CSV** and **TXT** files in S3.
* Performs **simple word count analysis**.
* Stores results in **DynamoDB**.
* Sends **summary email** via SNS.
* Supports **multiple or single file uploads**.
* Easy cleanup of resources created in the last 24 hours.

---

## Project Structure

```
.
├── deploy.py       # Script to deploy all AWS resources
├── cleanup.py      # Script to remove all resources from the last 24 hours
├── README.md       # This documentation
```

---

## Prerequisites

* Python 3.x
* AWS CLI configured with access key and secret
* Boto3 installed (`pip install boto3`)

---

## Deployment

1. Run the deploy script:

```bash
python deploy.py
```

2. Enter comma-separated email addresses to subscribe to the SNS topic.

3. The script will:

   * Create **source and target S3 buckets**.
   * Create **SNS topic** and subscribe provided emails.
   * Create **IAM role** for Lambda.
   * Create **DynamoDB table**.
   * Deploy Lambda function for word analysis.
   * Add **S3 trigger** for the Lambda function.

4. Once deployed, upload text or CSV files to the **source bucket**.
   The Lambda function will:

   * Analyze words.
   * Store results in DynamoDB.
   * Copy the file to the **target bucket**.
   * Send a **summary email** via SNS.

---

## Cleanup

To remove all resources created in the last 24 hours, run:

```bash
python cleanup.py
```

This script will:

* Delete **Lambda functions**.
* Delete **IAM roles** and inline policies.
* Delete **S3 buckets** and all contents.
* Delete **SNS topics** and unsubscribe emails.
* Delete **DynamoDB tables**.

---

## Notes

* Both scripts are **self-contained** and require only Python and Boto3.
* All resources are **timestamped** to avoid name conflicts.
* SNS subscribers must **confirm subscription** via email to receive notifications.

---

## Example Use

1. Deploy:

```bash
python deploy.py
```

2. Upload `example.txt` or `example.csv` to the source S3 bucket.
3. Receive an email summary of word counts.
4. When testing is done:

```bash
python cleanup.py
```

---

This setup is ideal for **learning serverless architectures**, **word analysis pipelines**, and **AWS automation** using Python.
