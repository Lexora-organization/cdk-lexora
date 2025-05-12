import os
import json
import boto3
import time
from botocore.exceptions import ClientError
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

# 환경 변수
OPENSEARCH_ENDPOINT = os.environ["OPENSEARCH_ENDPOINT"]
OPENSEARCH_INDEX = os.environ.get("OPENSEARCH_INDEX", "lexora-embeddings")
REGION = os.environ.get("AWS_REGION", "ap-northeast-2")

# Bedrock
bedrock = boto3.client("bedrock-runtime", region_name=REGION)

# OpenSearch 설정
credentials = boto3.Session().get_credentials()
auth = AWSV4SignerAuth(credentials, REGION, "es")

opensearch = OpenSearch(
    hosts=[{"host": OPENSEARCH_ENDPOINT, "port": 443}],
    http_auth=auth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)

def embed_text(text: str):
    payload = {
        "inputText": text,
        "dimensions": 512,         # 원하는 차원 수
        "normalize": True          # 단위 벡터 정규화
    }

    try:
        response = bedrock.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",   # 정확한 모델 ID
            body=json.dumps(payload),
            accept="application/json",
            contentType="application/json"
        )

        result = json.loads(response['body'].read())

        if "embedding" not in result:
            raise ValueError("응답에 'embedding' 필드 없음")

        return result["embedding"]

    except Exception as e:
        raise Exception(f"[ERROR] 임베딩 실패: {e}")


def index_to_opensearch(doc: dict):
    try:
        response = opensearch.index(
            index=OPENSEARCH_INDEX,
            id=f"{doc['userId']}_{doc['fileId']}_{doc['chunkIndex']}",
            body=doc,
        )
        return response
    except Exception as e:
        raise Exception(f"[ERROR] OpenSearch 저장 실패 - {e}")

def update_file_status(file_id: str, status: str, error_msg: str = None):
    table = boto3.resource("dynamodb").Table(os.environ["FILES_TABLE"])
    update_expr = "SET #s = :s, updatedAt = :u"
    expr_attr = {":s": status, ":u": int(time.time())}
    attr_names = {"#s": "status"}
    if error_msg:
        update_expr += ", errorMsg = :e"
        expr_attr[":e"] = error_msg
    try:
        table.update_item(
            Key={"fileId": file_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_attr,
            ExpressionAttributeNames=attr_names,
        )
        print(f"[INFO] 상태 업데이트 완료 - fileId={file_id}, status={status}")
    except Exception as e:
        print(f"[ERROR] DynamoDB 상태 업데이트 실패: {e}")

def lambda_handler(event, context):
    print("[INFO] Lexora Embed Lambda triggered")
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            print(f"[INFO] Message body: {body}")

            file_id = body["fileId"]
            user_id = body["userId"]
            chunks = body.get("chunks", [])

            if not chunks:
                print(f"[WARNING] chunks가 없음 - fileId={file_id}")
                continue

            for chunk in chunks:
                chunk_index = chunk["chunkIndex"]
                content = chunk["content"]
                page_number = chunk.get("page")

                embedding = embed_text(content)

                doc = {
                    "fileId": file_id,
                    "userId": user_id,
                    "chunkIndex": chunk_index,
                    "content": content,
                    "embedding": embedding,
                    "timestamp": int(time.time())
                }

                # page 정보가 있다면 추가
                if page_number is not None:
                    doc["page"] = page_number
                else:
                    print(f"[INFO] chunk={chunk_index}에는 page 정보가 없습니다.")


                index_to_opensearch(doc)
                print(f"[INFO] 임베딩 저장 완료 - fileId={file_id}, chunk={chunk_index}, page={page_number}")

            update_file_status(file_id, "embedded")

        except Exception as e:
            print(f"[ERROR] 처리 실패 - fileId={body.get('fileId', 'N/A')}, error={e}")

