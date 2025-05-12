import os
import json
import time
import re
import tempfile
import textwrap
from typing import List
from urllib.parse import urlparse

import boto3
import pdfplumber
from botocore.exceptions import ClientError

# 환경 변수
CONVERTED_BUCKET = os.getenv("CONVERTED_BUCKET")
EMBEDDING_QUEUE_URL = os.getenv("EMBEDDING_QUEUE_URL")
FILES_TABLE = os.getenv("FILES_TABLE")

# AWS 리소스
s3 = boto3.client("s3")
sqs = boto3.client("sqs")
dynamodb = boto3.resource("dynamodb")
files_table = dynamodb.Table(FILES_TABLE)


def parse_s3_path(s3_path: str):
    parsed = urlparse(s3_path)
    return parsed.netloc, parsed.path.lstrip("/")


def extract_text_from_pdf(bucket: str, key: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        try:
            s3.download_file(bucket, key, tmp.name)
        except ClientError as e:
            raise Exception(f"S3 다운로드 실패: {e}")

        with pdfplumber.open(tmp.name) as pdf:
            texts = []
            extracted = []

            for page_num, page in enumerate(pdf.pages):
                txt = page.extract_text()
                if txt:
                    texts.append(txt)
                    extracted.append(True)
                else:
                    print(f"[WARN][{key}] Page {page_num}에서 텍스트 추출 실패")
                    extracted.append(False)

            if not any(extracted):
                raise Exception("PDF 전체에서 텍스트 추출 실패")

        return "\n\n".join(texts)


def split_into_chunks(text: str, max_chars: int = 1000, overlap: int = 200) -> List[str]:
    text = re.sub(r"\n{2,}", "\n\n", text)
    text = text.strip()
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 <= max_chars:
            current_chunk += (para + "\n\n")
        else:
            chunks.append(current_chunk.strip())
            overlap_text = current_chunk[-overlap:] if overlap > 0 else ""
            current_chunk = overlap_text + para + "\n\n"

    if current_chunk:
        chunks.append(current_chunk.strip())

    
    return chunks


def send_to_embedding_queue(message: dict):
    try:
        sqs.send_message(
            QueueUrl=EMBEDDING_QUEUE_URL,
            MessageBody=json.dumps(message)
        )
    except Exception as e:
        raise Exception(f"SQS 전송 실패: {e}")


def update_file_status(file_id: str, status: str, error_msg: str = None):
    update_expr = "SET #s = :s, updatedAt = :u"
    expr_values = {
        ":s": status,
        ":u": int(time.time())
    }
    expr_attr_names = {"#s": "status"}

    if error_msg:
        update_expr += ", errorMsg = :e"
        expr_values[":e"] = error_msg

    try:
        files_table.update_item(
            Key={"fileId": file_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_values
        )
        print(f"[INFO] fileId={file_id} 상태 업데이트 → {status}")
    except Exception as e:
        raise Exception(f"DynamoDB 상태 업데이트 실패: {e}")

def extract_text_by_page(bucket: str, key: str) -> List[dict]:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        s3.download_file(bucket, key, tmp.name)
        with pdfplumber.open(tmp.name) as pdf:
            result = []
            for page_num, page in enumerate(pdf.pages):
                txt = page.extract_text()
                if txt:
                    result.append({"page": page_num + 1, "text": txt})  # 페이지 번호는 1부터
                else:
                    print(f"[WARN][{key}] Page {page_num + 1}에서 텍스트 추출 실패")
            if not result:
                raise Exception("PDF 전체에서 텍스트 추출 실패")
            return result


def split_chunks_with_page_info(pages: List[dict], max_chars=1000, overlap=200) -> List[dict]:
    chunks = []
    for p in pages:
        text = p["text"].strip()
        paragraphs = [para.strip() for para in re.split(r'\n{2,}', text) if para.strip()]
        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) + 2 <= max_chars:
                current_chunk += para + "\n\n"
            else:
                if current_chunk.strip():
                    chunks.append({"content": current_chunk.strip(), "page": p["page"]})
                overlap_text = current_chunk[-overlap:] if overlap > 0 else ""
                current_chunk = overlap_text + para + "\n\n"
        if current_chunk.strip():
            chunks.append({"content": current_chunk.strip(), "page": p["page"]})
    return chunks

def lambda_handler(event, context):
    print("[INFO] Lexora Extract Lambda triggered")

    for record in event.get("Records", []):
        file_id = None
        try:
            body = json.loads(record["body"])
            print(f"[INFO] SQS 메시지 수신: {body}")

            file_id = body["fileId"]
            user_id = body["userId"]
            s3_path = body["s3Path"]

            bucket, key = parse_s3_path(s3_path)
            print(f"[INFO] S3 경로 파싱 완료 - bucket: {bucket}, key: {key}")

            print("[INFO] PDF 텍스트 추출 시작")
            pages = extract_text_by_page(bucket, key)
            print(f"[INFO] 페이지 수: {len(pages)}")

            print("[INFO] chunk 분할 시작")
            chunks = split_chunks_with_page_info(pages, max_chars=1000, overlap=200)
            if not chunks:
                raise Exception("chunk 분할 실패 - 결과 없음")
            print(f"[INFO] chunk 분할 완료 - 총 {len(chunks)}개")

            chunk_payload = {
                "fileId": file_id,
                "userId": user_id,
                "chunks": [
                    {
                        "chunkIndex": i,
                        "content": chunk["content"],
                        "page": chunk["page"]  # 여기 추가
                    }
                    for i, chunk in enumerate(chunks)
                ]
            }
            send_to_embedding_queue(chunk_payload)
            print(f"[INFO] 전체 chunk 전송 완료 - 총 {len(chunks)}개")

            update_file_status(file_id, "extracted")
            print(f"[INFO] 처리 완료 - fileId={file_id}, status=extracted")

        except Exception as e:
            print(f"[ERROR] 처리 실패 - {e}")
            if file_id:
                try:
                    update_file_status(file_id, "failed", str(e))
                    print(f"[INFO] 실패 상태 기록 완료 - fileId={file_id}, status=failed")
                except Exception as e2:
                    print(f"[ERROR] DynamoDB 상태 업데이트 실패 - {e2}")
            else:
                print("[ERROR] fileId 없음 - 상태 업데이트 생략")
