import os
import json
import tempfile
import time
import glob
import boto3
from botocore.exceptions import ClientError

# 환경 변수
RAW_BUCKET = os.getenv("RAW_BUCKET", "lexora-raw-files-bucket")
CONVERTED_BUCKET = os.getenv("CONVERTED_BUCKET", "lexora-converted-files-bucket")
FILES_TABLE = os.getenv("FILES_TABLE", "lexora-files")
VERSIONS_TABLE = os.getenv("VERSIONS_TABLE", "lexora-file-versions")
EXTRACT_QUEUE_URL = os.getenv("EXTRACT_QUEUE_URL")


# AWS 클라이언트
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
files_table = dynamodb.Table(FILES_TABLE)
sqs = boto3.client("sqs")


def lambda_handler(event, context):
    print("[INFO] Lexora ConvPDF Lambda triggered")
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            print(f"[INFO] Message body: {body}")
            _convert_or_copy(body)
        except Exception as e:
            print(f"[ERROR] 처리 실패: {e}")
            if "fileId" in body:
                _update_status(body["fileId"], "failed", str(e))


def _convert_or_copy(message: dict):
    file_id = message["fileId"]
    key = message["key"]
    mime_type = message.get("mimeType", "")
    owner_id = message.get("ownerId", "unknown")

    # 업로드 날짜 추출
    try:
        date_part = "/".join(key.split("/")[1:4])  # yyyy/mm/dd
        converted_key = f"{owner_id}/{date_part}/{file_id}.pdf"
    except Exception as e:
        raise Exception(f"key에서 날짜 경로 추출 실패: {e}")

    if mime_type == "application/pdf" or key.lower().endswith(".pdf"):
        print("[INFO] PDF → 그대로 복사")
        _copy_pdf_to_converted(key, converted_key)
    else:
        print("[INFO] 비PDF → LibreOffice 변환")
        _convert_and_store_pdf(key, converted_key)

    print("[INFO] 변환 완료 → status 업데이트")
    _update_status(file_id, "converted")

    # 추출 단계로 메시지 전송
    _send_to_extract_queue({
        "fileId": file_id,
        "userId": owner_id,
        "s3Path": f"s3://{CONVERTED_BUCKET}/{converted_key}"
    })



def _copy_pdf_to_converted(src_key: str, dest_key: str):
    try:
        # S3 객체 존재 확인 (존재하지 않으면 ClientError)
        s3.head_object(Bucket=RAW_BUCKET, Key=src_key)
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            raise Exception(f"[ERROR] S3 객체 없음: {src_key}")
        else:
            raise Exception(f"[ERROR] S3 오류 발생: {e}")

    copy_source = {"Bucket": RAW_BUCKET, "Key": src_key}
    s3.copy_object(Bucket=CONVERTED_BUCKET, CopySource=copy_source, Key=dest_key)
    print(f"[INFO] ✅ PDF 복사 완료: s3://{CONVERTED_BUCKET}/{dest_key}")


def _convert_and_store_pdf(src_key: str, dest_key: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        local_input = os.path.join(tmpdir, os.path.basename(src_key))
        s3.download_file(RAW_BUCKET, src_key, local_input)
        print(f"[INFO] 원본 다운로드 완료: {local_input}")

        # LibreOffice 사용자 프로필 디렉토리 설정
        user_install_path = os.path.join(tmpdir, "lo_profile")
        os.makedirs(user_install_path, exist_ok=True)
        os.environ["HOME"] = user_install_path
        os.environ["USER_INSTALLATION"] = f"file://{user_install_path}"

        result = os.system(f"libreoffice --headless --nologo --convert-to pdf --outdir {tmpdir} {local_input}")
        print(f"[INFO] LibreOffice 실행 결과: {result}")

        pdf_files = [f for f in glob.glob(os.path.join(tmpdir, "*.pdf")) if os.path.isfile(f)]
        if not pdf_files:
            raise Exception("PDF 변환 실패: 생성된 PDF 없음")

        with open(pdf_files[0], "rb") as f:
            s3.upload_fileobj(f, CONVERTED_BUCKET, dest_key)
        print(f"[INFO] PDF 변환 및 업로드 완료: s3://{CONVERTED_BUCKET}/{dest_key}")



def _update_status(file_id: str, status: str, error_msg: str = None):
    update_expr = "SET #s = :s, updatedAt = :u"
    expr_values = {":s": status, ":u": int(time.time())}
    if error_msg:
        update_expr += ", errorMsg = :e"
        expr_values[":e"] = error_msg
    try:
        files_table.update_item(
            Key={"fileId": file_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=expr_values
        )
        print(f"[INFO] fileId={file_id} 상태 → {status}")
    except Exception as e:
        print(f"[ERROR] DynamoDB 상태 업데이트 실패: {e}")


def _send_to_extract_queue(message: dict):
    try:
        sqs.send_message(
            QueueUrl=EXTRACT_QUEUE_URL,
            MessageBody=json.dumps(message)
        )
        print(f"[INFO] 추출 큐로 전송 완료: {message['fileId']}")
    except Exception as e:
        raise Exception(f"SQS 전송 실패: {e}")
