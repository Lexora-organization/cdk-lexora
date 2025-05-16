#handler.py
import json
import boto3
import uuid
import time
import os
import re
import traceback
from decimal import Decimal
from urllib.parse import quote
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

from utils import (
    get_authenticated_user,
    response,
    validate_file_ids,
    get_prompt_embedding,
    search_similar_chunks,
    build_claude_messages,
    invoke_claude,
    build_marked_prompt,
    parse_claude_response,
    generate_questions_from_chunks,
    get_query_session,
    query_sessions_table,
    cors_response,
    sample_chunks_from_opensearch,
    NO_DOC_MESSAGE,
    invoke_claude_converse_stream,
    SYSTEM_PROMPT
)
def generate_questions_v2(event, context):
    try:
        user_id, auth_resp = get_authenticated_user(event)
        if not user_id:
            return auth_resp

        body = json.loads(event.get("body", "{}"))
        file_ids = body.get("fileIds", [])
        if not file_ids or not isinstance(file_ids, list):
            return response(False, "fileIds가 누락되었거나 형식이 잘못되었습니다.", status_code=400)
        validate_file_ids(file_ids, user_id)

        # OpenSearch에서 랜덤 샘플링
        sampled_contents = sample_chunks_from_opensearch(file_ids, sample_size=3)
        if not sampled_contents:
            return response(False, "문서에서 샘플 청크를 가져올 수 없습니다.", status_code=400)

        # 프롬프트 생성
        prompt = f"""
다음 세 문단을 참고하여 사용자가 물어볼 만한 질문 3~5개를 생성해주세요.

[조건]
1. 각 질문은 간결·명확하게, 최대 20자 이내로 작성합니다.
2. 출력 형식은 순수 JSON 객체 하나로만 구성합니다.
3. JSON 키는 반드시 "questions"여야 하며, 값은 문자열 배열입니다.
4. JSON 외 다른 설명, 마크다운, 번호 매기기, 불릿포인트는 절대 포함하지 않습니다.

[입력 문단 예시]
문단1: 이 정책은 만 18세 이상 대한민국 국민이 신청할 수 있습니다.
문단2: 신청 시 주민등록등본, 신분증 사본을 제출해야 합니다.
문단3: 심사 기간은 접수일로부터 14영업일 이내이며, 결과는 이메일로 통보됩니다.

[출력 예시]
{{
  "questions": [
    "신청 자격은 무엇인가요?",
    "제출해야 할 서류는 무엇인가요?",
    "심사 기간은 얼마나 걸리나요?"
  ]
}}

※ 반드시 위의 규칙을 따라 JSON 객체 형태로만 출력하세요. 단일 문자열이나 다른 형식은 허용되지 않습니다.

------------------------------

이제 위 형식을 참고하여 실제 문단에 대해 질문을 생성하세요.

[실제 문단]
문단1: {sampled_contents[0]}
문단2: {sampled_contents[1]}
문단3: {sampled_contents[2]}

"""
        # Claude 호출 → JSON 파싱 (간단 래퍼)
        raw = invoke_claude([{"role": "user", "content": [{"type": "text", "text": prompt}]}])
        parsed = json.loads(raw)
        questions = [q.strip() for q in parsed.get("questions", []) if isinstance(q, str)]

        return response(True, "추천 질문 생성 완료", {
            "recommendedQuestions": questions
        })

    except PermissionError as e:
        return response(False, str(e), status_code=403)
    except ValueError as e:
        return response(False, str(e), status_code=400)
    except Exception as e:
        print("[ERROR] 추천 질문 생성 실패:", e)
        traceback.print_exc()
        return response(False, "추천 질문 생성 중 오류 발생", error=str(e), status_code=500)

def query_send(event, context):
    try:
        # 사용자 인증 (user session → userId 추출)
        user_id, auth_resp = get_authenticated_user(event)
        if not user_id:
            return auth_resp

        body = json.loads(event.get("body", "{}"))
        query_session_id = body.get("querySessionId")
        prompt = body.get("prompt")
        file_ids = body.get("fileIds")

        # 필수 값 체크
        if not query_session_id:
            return response(False, "querySessionId가 누락되었습니다.", status_code=400)
        if not prompt:
            return response(False, "prompt가 누락되었습니다.", status_code=400)
        if file_ids is not None and (not isinstance(file_ids, list) or not file_ids):
            return response(False, "fileIds가 올바른 형식이 아닙니다.", status_code=400)

        # 세션 존재 및 권한 체크
        session_item = get_query_session(query_session_id, user_id)

        # fileIds가 있다면 문서 기반 유사 chunk 검색
        context_chunks = []
        if file_ids:
            validate_file_ids(file_ids, user_id)
            embedding = get_prompt_embedding(prompt)
            context_chunks = search_similar_chunks(embedding, file_ids)

        # Claude 프롬프트 구성
        if context_chunks:
            full_prompt, footnotes = build_marked_prompt(prompt, context_chunks)
        else:
            full_prompt = f"{NO_DOC_MESSAGE}\n\n질문: {prompt}"
            footnotes = []

        # Claude 3.5 스트리밍 호출
        answer_text = invoke_claude_converse_stream(full_prompt, system_prompt=SYSTEM_PROMPT)

        # 세션 히스토리 저장
        session_item["chatHistory"].append({
            "role": "user",
            "content": [{"type": "text", "text": prompt}]
        })
        session_item["chatHistory"].append({
            "role": "assistant",
            "content": [{"type": "text", "text": answer_text}]
        })
        session_item["lastActiveAt"] = int(time.time())
        query_sessions_table.put_item(Item=session_item)

        return response(True, "질의 응답 완료", {
            "querySessionId": query_session_id,
            "answer": answer_text,
            "footnotes": footnotes
        })

    except PermissionError as e:
        return response(False, str(e), status_code=403)
    except ValueError as e:
        return response(False, str(e), status_code=400)
    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return response(False, "처리 중 오류 발생", error=str(e), status_code=500)




def lambda_handler(event, context):
    print("Received event:", json.dumps(event))
    method = event.get("httpMethod", "").upper()
    path = event.get("path", "").lower()

    if method == "OPTIONS":
        return cors_response({"statusCode": 200, "body": json.dumps({"message": "CORS OK"})})
    if path == "/query" and method == "POST":
        return query_send(event, context)
    elif path == "/generate_query" and method == "POST":
        return generate_questions_v2(event, context)

    return cors_response({
        "statusCode": 404,
        "body": json.dumps({"message": "잘못된 경로입니다.", "path": path}, ensure_ascii=False)
    })
