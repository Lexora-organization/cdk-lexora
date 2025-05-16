# utils.py
import ast
import json
import os
import time
import re
from decimal import Decimal
import boto3
import uuid
from boto3.dynamodb.conditions import Key
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
import random

# 환경 변수
FILES_TABLE = os.getenv("FILES_TABLE")
QUERY_SESSIONS_TABLE = os.getenv("QUERY_SESSIONS_TABLE")
OPENSEARCH_ENDPOINT = os.getenv("OPENSEARCH_ENDPOINT")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "ap-northeast-2")
# constants.py 또는 utils.py 내 상단
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"  
CLAUDE_MODEL_ID  = "anthropic.claude-3-5-sonnet-20240620-v1:0"

# MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0" 
# MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

# MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
# MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"

NO_DOC_MESSAGE = "관련 문서를 찾을 수 없어서 일반 답변을 제공합니다."


# AWS 리소스
dynamodb = boto3.resource("dynamodb")
files_table = dynamodb.Table("lexora-files")
sessions_table = dynamodb.Table("lexora-sessions")
query_sessions_table = dynamodb.Table(os.environ["QUERY_SESSIONS_TABLE"])

bedrock = boto3.client("bedrock-runtime", region_name="ap-northeast-2")



# OpenSearch 설정
credentials = boto3.Session().get_credentials()
auth = AWSV4SignerAuth(credentials, "ap-northeast-2", "es")
opensearch = OpenSearch(
    hosts=[{"host": os.environ["OPENSEARCH_ENDPOINT"], "port": 443}],
    http_auth=auth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)

# 상수
SYSTEM_PROMPT = """당신은 제공된 문서 조각이 있다면 이를 활용하고, 없다면 일반적인 정보를 바탕으로 답변하는 AI 어시스턴트입니다.

## 응답 형식 규칙:
1. 최종 응답은 반드시 유효한 JSON 객체 형식이어야 합니다.
2. JSON에는 다음 두 개의 필드를 포함할 수 있습니다:
   - `answer`: 질문에 대한 마크다운(Markdown) 형식의 문자열
   - `footnotes`: 실제로 인용된 문서 조각 목록 (선택적)
3. 문서를 인용한 경우에는 `answer` 안에 [1], [2] 형태로 각 인용을 표시하고 `footnotes` 필드도 포함해야 합니다.
4. 문서가 없거나 인용이 불가능할 경우에는 `answer`만 포함하며, 절대 `[1]`, `[2]` 형태의 인용 마커를 넣지 마세요.
5. 응답은 반드시 사용자의 질문 언어에 맞추어 작성하세요. 예: 질문이 영어면 영어로, 한국어면 한국어로.
6. `footnotes`는 다음과 같은 형식의 리스트입니다:
   { "refId": 1, "fileName": "문서명.pdf", "page": 3 }
7. `refId`는 `answer` 내의 인용 번호와 일치해야 합니다.
8. JSON 응답 외에 다른 설명이나 주석을 추가하지 마세요.
9. 응답 내 개행은 반드시 \\n 형태의 이스케이프 문자로 포함하세요.

## 예시 (문서를 인용한 경우):
{
  "answer": "정책 적용은 다음 절차에 따라 이루어집니다. [1]\\n\\n### 예시 코드\\n```python\\ndef greet(name):\\n    return f\"Hello, {name}\"\\n```\\n\\n### 터미널 명령어\\n```bash\\naws s3 ls\\n```\\n\\n### 요약표\\n| 단계 | 설명 |\\n|------|------|\\n| 1단계 | 신청 접수 |\\n| 2단계 | 서류 심사 |\\n| 3단계 | 최종 승인 |",
  "footnotes": [
    { "refId": 1, "fileName": "업무처리매뉴얼.pdf", "page": 12 }
  ]
}

## 예시 (문서가 없는 경우):
{
  "answer": "해당 명령어는 AWS CLI를 통해 S3 버킷 목록을 확인하는 데 사용됩니다.\\n\\n```bash\\naws s3 ls\\n```"
}
※ 반드시 위의 규칙을 따라 JSON 객체 형태로 감싼 결과만 출력하세요. 단일 문자열로만 답변하지 마세요.

이제 위 형식을 참고하여 사용자의 질문에 정확히 답변하세요."""


NO_DOC_MESSAGE = "관련 문서를 찾을 수 없어서 일반 답변을 제공합니다."

# CORS 설정
def cors_response(resp):
    resp["headers"] = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "OPTIONS, GET, POST, PUT, DELETE",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"
    }
    return resp

def response(success, message, data=None, error=None, status_code=200):
    body = {"success": success, "message": message}
    if data is not None:
        body["data"] = convert_decimals(data)
    if error is not None:
        body["error"] = error
    return {
        "statusCode": status_code,
        "body": json.dumps(body, ensure_ascii=False),
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "OPTIONS, GET, POST, PUT, DELETE",
            "Access-Control-Allow-Headers": "Content-Type, Authorization"
        }
    }

def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    else:
        return obj

def get_authenticated_user(event):
    headers = event.get("headers", {})
    session_id = headers.get("Authorization")
    if not session_id:
        return None, response(False, "세션이 필요합니다.", status_code=401)

    session_res = sessions_table.get_item(Key={"sessionId": session_id})
    session = session_res.get("Item")
    now = int(time.time())
    if not session or not session.get("isValid") or session.get("expiresAt", 0) < now:
        return None, response(False, "유효하지 않은 세션입니다.", status_code=401)

    return session["userId"], None

def generate_session_title(prompt, max_length=30):
    if not prompt:
        return "새로운 세션"
    cleaned = re.sub(r"\s+", " ", prompt).strip()
    cleaned = re.sub(r"[\"\'\\]", "", cleaned)
    return cleaned[:max_length] + "..." if len(cleaned) > max_length else cleaned

def get_prompt_embedding(text):
    payload = {
        "inputText": text,
        "dimensions": 512,
        "normalize": True
    }
    res = bedrock.invoke_model(
        modelId=EMBED_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(payload)
    )
    return json.loads(res["body"].read())["embedding"]

def search_similar_chunks(embedding_vector, file_ids, top_k=10, min_score=0.5):
    query = {
        "size": top_k,
        "query": {
            "bool": {
                "filter": [{"terms": {"fileId": file_ids}}],
                "must": {
                    "knn": {
                        "embedding": {
                            "vector": embedding_vector,
                            "k": top_k
                        }
                    }
                }
            }
        }
    }
    res = opensearch.search(index=os.environ["OPENSEARCH_INDEX"], body=query)

    results = []
    for hit in res["hits"]["hits"]:
        score = hit["_score"]
        if score >= min_score:
            src = hit["_source"]
            file_id = src["fileId"]
            chunk_index = src["chunkIndex"]
            content = src["content"]
            page = src.get("page")

            try:
                file_meta = files_table.get_item(Key={"fileId": file_id}).get("Item")
                file_name = file_meta["fileName"] if file_meta else "Unknown"
            except Exception as e:
                print(f"[WARNING] Failed to fetch fileName for {file_id}: {e}")
                file_name = "Unknown"

            results.append({
                "fileId": file_id,
                "fileName": file_name,
                "chunkIndex": chunk_index,
                "content": content,
                "page": page, 
                "score": score
            })

    return results



def build_marked_prompt(prompt, chunks):
    prompt_parts = []
    footnotes = []
    file_names = list({c['fileName'] for c in chunks})  # 중복 제거

    # 문서 목록 헤더
    doc_header = "## 참고 문서 목록\n" + "\n".join(f"- {fn}" for fn in file_names)

    for i, c in enumerate(chunks):
        ref_id = i + 1
        marker = f"[{ref_id}]"
        prompt_parts.append(f"{marker} {c['content']}")

        footnote = {
            "refId": ref_id,
            "fileName": c["fileName"],
        }
        if "page" in c and c["page"] is not None:
            footnote["page"] = c["page"]
        footnotes.append(footnote)

    joined_chunks = "\n".join(prompt_parts)
    full_prompt = (
        SYSTEM_PROMPT + "\n\n"
        f"참고 문서 제목 : {doc_header}\n\n"
        f"참고 문서 내용 : {joined_chunks}\n\n"
        f"질문: {prompt}"
    )

    return full_prompt, footnotes

def validate_file_ids(file_ids, user_id):
    for fid in file_ids:
        r = files_table.get_item(Key={"fileId": fid})
        i = r.get("Item")
        if not i or i.get("ownerId") != user_id or i.get("status") != "embedded":
            raise ValueError(f"fileId={fid}는 사용 불가능한 상태입니다.")

# 세션 조회 전용 (권한 확인 포함)
def get_query_session(query_session_id, user_id):
    res = query_sessions_table.get_item(Key={"querySessionId": query_session_id})
    session_item = res.get("Item")
    if not session_item:
        raise ValueError("세션이 존재하지 않습니다.")
    if session_item["userId"] != user_id:
        raise PermissionError("세션 접근 권한이 없습니다.")
    return session_item

# 세션 생성 전용
def create_new_query_session(user_id, prompt, session_title=None):
    query_session_id = str(uuid.uuid4())
    title = session_title or generate_session_title(prompt)
    timestamp = int(time.time())
    session_item = {
        "querySessionId": query_session_id,
        "userId": user_id,
        "sessionTitle": title,
        "sessionStatus": "active",
        "lastActiveAt": timestamp,
        "chatHistory": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ]
    }
    query_sessions_table.put_item(Item=session_item)
    return session_item


def build_claude_messages(prompt, file_ids, context_chunks, chat_history):
    messages = []

    # 히스토리 반영 (최근 10개만)
    for msg in chat_history[-10:]:
        messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    # SYSTEM_PROMPT는 마지막 질문에 병합
    if context_chunks:
        full_prompt, _ = build_marked_prompt(prompt, context_chunks)
        merged_prompt = f"{SYSTEM_PROMPT}\n\n{full_prompt}"
    else:
        merged_prompt = f"{SYSTEM_PROMPT}\n\n{NO_DOC_MESSAGE}\n\n질문: {prompt}"


    # 시스템 프롬프트 포함된 현재 질문만 추가
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": merged_prompt}]
    })

    return messages


def invoke_claude_converse_stream(prompt: str, system_prompt: str = SYSTEM_PROMPT):
    client = boto3.client("bedrock-runtime", region_name="ap-northeast-2")

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": system_prompt,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt}
                ]
            }
        ],
        "max_tokens": 3000,
        "temperature": 0.8,
        "top_p": 0.9,
        "top_k": 250
    }

    response = client.invoke_model_with_response_stream(
        modelId=CLAUDE_MODEL_ID,
        body=json.dumps(body),
        contentType="application/json"
    )

    result_text = ""
    for event in response["body"]:
        chunk = json.loads(event["chunk"]["bytes"])
        if chunk.get("type") == "content_block_delta":
            result_text += chunk["delta"].get("text", "")

    return result_text.strip()



def invoke_claude(messages):
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 3000,
        "temperature": 0.8,
        "top_p": 0.9,
        "top_k": 250,
        "stop_sequences": [],
        "messages": messages
    }

    claude_res = bedrock.invoke_model(
        modelId=CLAUDE_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(payload)
    )

    result = json.loads(claude_res["body"].read())
    content = result.get("content", [])
    if not content or not isinstance(content, list):
        raise ValueError("Claude 응답이 비어 있거나 잘못되었습니다.")

    return content[0].get("text", "").strip()

def parse_claude_response(raw_text):
    if not raw_text:
        raise ValueError("Claude 응답이 비어 있습니다.")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        try:
            # 일단 줄바꿈, 탭 등 잘못된 문자 제거
            cleaned = re.sub(r"[\x00-\x1F]+", "", raw_text)
            return json.loads(cleaned)
        except Exception:
            return ast.literal_eval(raw_text)
        


def generate_questions_from_chunks(chunks, max_questions=5):
    if not chunks:
        raise ValueError("추천 질문 생성을 위한 chunk가 없습니다.")

    # Claude에게 전달할 SYSTEM 수준 프롬프트 템플릿
    QUESTION_GENERATION_PROMPT_TEMPLATE = """당신은 주어진 문서 내용을 기반으로 사용자가 물어볼 수 있는 적절한 질문 목록을 생성하는 AI입니다.

## 응답 규칙:
1. 반드시 아래 JSON 형식으로만 응답하세요.
2. 각 질문은 간결하고 명확한 문장으로 작성합니다.
3. 문서를 요약하거나 설명하지 마세요. 반드시 질문만 출력합니다.
4. 질문은 최대 3개, 최소 3개 작성하세요.
5. 응답은 다음 형식을 따라야 합니다:

{
  "questions": [
    "이 정책은 누가 신청할 수 있나요?",
    "신청 절차는 어떻게 되나요?",
    "필수 제출 서류는 무엇인가요?"
  ]
}"""
    # 상위 N개의 chunk만 context로 사용 (default: 상위 3개)
    top_chunks = chunks[:3]
    context = "\n\n".join(f"- {c['content']}" for c in top_chunks)

    # Claude에 넣을 프롬프트 생성
    prompt = QUESTION_GENERATION_PROMPT_TEMPLATE.replace("{context}", context)

    # Bedrock용 payload 생성
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1000,
        "temperature": 0.7,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}]
            }
        ]
    }

    # Claude 모델 호출
    claude_res = bedrock.invoke_model(
        modelId=CLAUDE_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(payload)
    )

    result = json.loads(claude_res["body"].read())
    raw_text = result["content"][0]["text"]

    # JSON 파싱
    try:
        parsed = json.loads(raw_text)
        questions = parsed.get("questions", [])
        if not isinstance(questions, list):
            raise ValueError("`questions` 필드는 리스트여야 합니다.")
        return [q.strip() for q in questions if q.strip()][:max_questions]
    except Exception as e:
        raise ValueError(f"Claude 응답 JSON 파싱 실패: {e}\n\n원본 응답:\n{raw_text}")
    

def sample_chunks_from_opensearch(file_ids: list[str], sample_size: int = 3) -> list[str]:
    """
    OpenSearch에서 file_ids에 해당하는 문서 청크를 랜덤 샘플링합니다.
    - fileId 필터링 후, function_score.random_score를 이용해 랜덤 추출
    - 반환값: content 문자열 리스트
    """
    # OpenSearch function_score + random_score 쿼리
    body = {
        "size": sample_size,
        "query": {
            "function_score": {
                "query": {
                    "bool": {
                        "filter": [
                            {"terms": {"fileId": file_ids}}
                        ]
                    }
                },
                "random_score": {}  
            }
        },
        "_source": ["content"]
    }

    resp = opensearch.search(index=OPENSEARCH_INDEX, body=body)
    hits = resp["hits"]["hits"]
    return [hit["_source"]["content"] for hit in hits]