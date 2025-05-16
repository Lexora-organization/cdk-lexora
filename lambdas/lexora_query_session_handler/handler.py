import os
import json
import time
import uuid
import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.conditions import Attr  # 수정 필요
from decimal import Decimal


dynamodb = boto3.resource("dynamodb")
query_sessions_table = dynamodb.Table(os.environ["QUERY_SESSIONS_TABLE"])
sessions_table = dynamodb.Table(os.environ["SESSIONS_TABLE"])  # 새 테이블 환경 변수 필요

def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    else:
        return obj


def cors_response(resp):
    resp["headers"] = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "OPTIONS, GET, POST, PATCH, DELETE",
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



def lambda_handler(event, context):
    print("Received event:", json.dumps(event))
    method = event.get("httpMethod", "GET")
    path = event.get("path", "")

    if method == "OPTIONS":
        return cors_response({"statusCode": 200, "body": json.dumps({"message": "CORS OK"})})

    user_id, auth_resp = get_authenticated_user(event)
    if not user_id:
        return auth_resp

    if path == "/query-session" and method == "POST":
        return create_query_session(event, user_id)
    elif path == "/query-session" and method == "GET":
        return list_query_sessions(user_id)
    elif path.startswith("/query-session/") and method == "GET":
        session_id = path.split("/")[-1]
        return get_query_session(user_id, session_id)
    elif path.startswith("/query-session/") and method == "PATCH":
        session_id = path.split("/")[-1]
        return update_query_session(event, user_id, session_id)
    elif path.startswith("/query-session/") and method == "DELETE":
        session_id = path.split("/")[-1]
        return delete_query_session(user_id, session_id)

    return response(False, "잘못된 경로입니다.", status_code=404)


def create_query_session(event, user_id):
    # 본문은 무시하거나, sessionTitle만 선택적으로 허용
    body = json.loads(event.get("body", "{}"))
    session_title = body.get("sessionTitle") or "새로운 세션"

    query_session_id = str(uuid.uuid4())
    session_item = {
        "querySessionId": query_session_id,
        "userId": user_id,
        "sessionTitle": session_title,
        "sessionStatus": "active",
        "lastActiveAt": int(time.time()),
        "chatHistory": []  # prompt 없이 생성되므로 초기 대화 없음
    }

    query_sessions_table.put_item(Item=session_item)

    return response(True, "세션이 생성되었습니다.", {
        "querySessionId": query_session_id,
        "sessionTitle": session_title
    })


def list_query_sessions(user_id):
    res = query_sessions_table.scan(
        FilterExpression=Attr("userId").eq(user_id)  # Key → Attr
    )
    items = res.get("Items", [])
    for item in items:
        item.pop("chatHistory", None)  # 목록에서는 생략
    return response(True, "세션 목록 조회 성공", {"sessions": items})



def get_query_session(user_id, session_id):
    res = query_sessions_table.get_item(Key={"querySessionId": session_id})
    item = res.get("Item")
    if not item or item["userId"] != user_id:
        return response(False, "세션을 찾을 수 없습니다.", status_code=404)
    return response(True, "세션 조회 성공", item)


def update_query_session(event, user_id, session_id):
    body = json.loads(event.get("body", "{}"))
    new_title = body.get("sessionTitle")
    if not new_title:
        return response(False, "sessionTitle이 누락되었습니다.", status_code=400)

    res = query_sessions_table.get_item(Key={"querySessionId": session_id})
    item = res.get("Item")
    if not item or item["userId"] != user_id:
        return response(False, "수정할 수 없습니다.", status_code=403)

    query_sessions_table.update_item(
        Key={"querySessionId": session_id},
        UpdateExpression="SET sessionTitle = :title, lastActiveAt = :ts",
        ExpressionAttributeValues={
            ":title": new_title,
            ":ts": int(time.time())
        }
    )
    return response(True, "세션 제목이 수정되었습니다.", {"querySessionId": session_id, "newTitle": new_title})


def delete_query_session(user_id, session_id):
    res = query_sessions_table.get_item(Key={"querySessionId": session_id})
    item = res.get("Item")
    if not item or item["userId"] != user_id:
        return response(False, "삭제할 수 없습니다.", status_code=403)

    query_sessions_table.delete_item(Key={"querySessionId": session_id})
    return response(True, "세션이 삭제되었습니다.", {"querySessionId": session_id})
