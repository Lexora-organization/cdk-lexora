import json
import boto3
import hashlib
import hmac
import uuid
import time
import os
from decimal import Decimal

# AWS DynamoDB 클라이언트
dynamodb = boto3.resource("dynamodb")
users_table = dynamodb.Table("lexora-users")
sessions_table = dynamodb.Table("lexora-sessions")  # 로그인 세션 테이블 추가
verification_table = dynamodb.Table("lexora-verification-tokens")

ses_client = boto3.client("ses", region_name="ap-northeast-2")

EMAIL_SENDER = os.getenv("EMAIL_SENDER", "lexora02095@gmail.com")
BASE_URL = os.getenv("EMAIL_VERIFY_URL", "https://lexora.cloud/verify-email")

# 환경 변수에서 salt key 가져오기
SALT_KEY = os.getenv("SALT_KEY", "your-default-salt")

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
    
# 비밀번호 해시 함수
def hash_password(password: str) -> str:
    return hmac.new(SALT_KEY.encode(), password.encode(), hashlib.sha256).hexdigest()

# 이메일 형식 검증 함수
def is_valid_email(email: str) -> bool:
    import re
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None

def convert_decimals(obj):
    if isinstance(obj, list):
        return [convert_decimals(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        # 소수점 있는지 확인하고 int 또는 float로 변환
        return int(obj) if obj % 1 == 0 else float(obj)
    else:
        return obj


def register(event, context):
    try:
        body = json.loads(event["body"])

        email = body.get("email")
        password = body.get("password")
        first_name = body.get("firstName")
        last_name = body.get("lastName")
        organization = body.get("organization")
        department = body.get("department")
        referral_source = body.get("referralSource")

        if not email or not is_valid_email(email):
            return response(False, "유효한 이메일을 입력하세요.", status_code=400)

        if not password or len(password) < 8:
            return response(False, "비밀번호는 8자 이상이어야 합니다.", status_code=400)

        if not first_name or not last_name:
            return response(False, "이름과 성은 필수입니다.", status_code=400)

        email_check = users_table.query(
            IndexName="email-index",
            KeyConditionExpression="email = :e",
            ExpressionAttributeValues={":e": email}
        )
        if email_check["Count"] > 0:
            return response(False, "이미 등록된 이메일입니다.", status_code=409)

        user_id = str(uuid.uuid4())
        now = int(time.time())
        password_hash = hash_password(password)

        user_item = {
            "userId": user_id,
            "email": email,
            "authProvider": "local",
            "passwordHash": password_hash,
            "firstName": first_name,
            "lastName": last_name,
            "organization": organization or "",
            "department": department or "",
            "referralSource": referral_source or "",
            "status": "unverified",
            "createdAt": now,
            "updatedAt": now,
            "lastLoginAt": None
        }

        users_table.put_item(Item=user_item)
        send_verification_email(user_id, email)

        return response(True, "회원가입이 완료되었습니다.", status_code=201, data={
            "userId": user_id,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "organization": organization,
            "department": department,
            "referralSource": referral_source,
            "createdAt": now,
            "status": "unverified"
        })

    except Exception as e:
        print("Register Error:", e)
        return response(False, "서버 오류", error=str(e), status_code=500)


def login(event, context):
    try:
        body = json.loads(event["body"])
        email = body.get("email")
        password = body.get("password")

        if not email or not is_valid_email(email):
            return response(False, "유효한 이메일을 입력하세요.", status_code=400)

        if not password:
            return response(False, "비밀번호를 입력하세요.", status_code=400)

        # 사용자 조회
        result = users_table.query(
            IndexName="email-index",
            KeyConditionExpression="email = :e",
            ExpressionAttributeValues={":e": email}
        )

        if result["Count"] == 0:
            return response(False, "이메일 또는 비밀번호가 올바르지 않습니다.", status_code=401)

        user = result["Items"][0]

        if hash_password(password) != user["passwordHash"]:
            return response(False, "이메일 또는 비밀번호가 올바르지 않습니다.", status_code=401)

        # 세션 생성
        session_id = str(uuid.uuid4())
        now = int(time.time())
        expires_at = now + 3600

        sessions_table.put_item(Item={
            "sessionId": session_id,
            "userId": user["userId"],
            "createdAt": now,
            "expiresAt": expires_at,
            "isValid": True,
            "ipAddress": event.get("requestContext", {}).get("identity", {}).get("sourceIp", ""),
            "userAgent": event.get("headers", {}).get("User-Agent", "")
        })

        users_table.update_item(
            Key={"userId": user["userId"]},
            UpdateExpression="SET lastLoginAt = :t",
            ExpressionAttributeValues={":t": now}
        )

        user.pop("passwordHash", None)

        if user.get("status") == "unverified":
            return response(False, "이메일 인증이 필요합니다.", data={
                "sessionId": session_id,
                "user": user
            })

        if user.get("status") == "inactive":
            return response(False, "비활성화된 계정입니다.", data={
                "sessionId": session_id,
                "user": user
            })


        return response(True, "로그인 성공", data={
                "sessionId": session_id,
                "user": user
            })

    except Exception as e:
        print("Login Error:", e)
        return response(False, "서버 오류", error=str(e), status_code=500)

def logout(event, context):
    try:
        headers = event.get("headers", {})
        session_id = headers.get("Authorization")

        if not session_id:
            return response(False, "세션이 필요합니다.", status_code=401)

        session = sessions_table.get_item(Key={"sessionId": session_id}).get("Item")

        if not session or not session.get("isValid", False):
            return response(False, "유효하지 않은 세션입니다.", status_code=401)

        sessions_table.update_item(
            Key={"sessionId": session_id},
            UpdateExpression="SET isValid = :f",
            ExpressionAttributeValues={":f": False}
        )

        return response(True, "로그아웃이 완료되었습니다.")

    except Exception as e:
        print("Logout Error:", e)
        return response(False, "서버 오류", error=str(e), status_code=500)


def get_me(event, context):
    try:
        headers = event.get("headers", {})
        session_id = headers.get("Authorization")

        if not session_id:
            return response(False, "세션이 필요합니다.", status_code=401)

        session_res = sessions_table.get_item(Key={"sessionId": session_id})
        session = session_res.get("Item")

        now = int(time.time())
        if not session or not session.get("isValid", False) or session.get("expiresAt", 0) < now:
            return response(False, "유효하지 않은 세션입니다.", status_code=401)

        user_id = session["userId"]
        user_res = users_table.get_item(Key={"userId": user_id})
        user = user_res.get("Item")

        if not user:
            return response(False, "사용자를 찾을 수 없습니다.", status_code=404)

        user.pop("passwordHash", None)
        return response(True, "사용자 정보 조회 성공", data=user)


    except Exception as e:
        print("GetMe Error:", e)
        return response(False, "서버 오류", error=str(e), status_code=500)


def modify_user(event, context):
    try:
        headers = event.get("headers", {})
        session_id = headers.get("Authorization")

        if not session_id:
            return response(False, "세션이 필요합니다.", status_code=401)

        session_res = sessions_table.get_item(Key={"sessionId": session_id})
        session = session_res.get("Item")

        now = int(time.time())
        if not session or not session.get("isValid", False) or session.get("expiresAt", 0) < now:
            return response(False, "유효하지 않은 세션입니다.", status_code=401)

        user_id = session["userId"]

        body = json.loads(event["body"])
        first_name = body.get("firstName")
        last_name = body.get("lastName")
        organization = body.get("organization")
        department = body.get("department")
        referral_source = body.get("referralSource")

        if not any([first_name, last_name, organization, department, referral_source]):
            return response(False, "수정할 정보가 없습니다.", status_code=400)

        update_expr = []
        expr_values = {}
        if first_name is not None:
            update_expr.append("firstName = :firstName")
            expr_values[":firstName"] = first_name
        if last_name is not None:
            update_expr.append("lastName = :lastName")
            expr_values[":lastName"] = last_name
        if organization is not None:
            update_expr.append("organization = :organization")
            expr_values[":organization"] = organization
        if department is not None:
            update_expr.append("department = :department")
            expr_values[":department"] = department
        if referral_source is not None:
            update_expr.append("referralSource = :referralSource")
            expr_values[":referralSource"] = referral_source

        update_expr.append("updatedAt = :updatedAt")
        expr_values[":updatedAt"] = now

        users_table.update_item(
            Key={"userId": user_id},
            UpdateExpression="SET " + ", ".join(update_expr),
            ExpressionAttributeValues=expr_values
        )

        return response(True, "사용자 정보가 수정되었습니다.")

    except Exception as e:
        print("ModifyUser Error:", e)
        return response(False, "서버 오류", error=str(e), status_code=500)

def withdraw_user(event, context):
    try:
        headers = event.get("headers", {})
        session_id = headers.get("Authorization")

        if not session_id:
            return response(False, "세션이 필요합니다.", status_code=401)

        session_res = sessions_table.get_item(Key={"sessionId": session_id})
        session = session_res.get("Item")

        now = int(time.time())
        if not session or not session.get("isValid", False) or session.get("expiresAt", 0) < now:
            return response(False, "유효하지 않은 세션입니다.", status_code=401)

        user_id = session["userId"]

        users_table.update_item(
            Key={"userId": user_id},
            UpdateExpression="SET #status = :status, updatedAt = :updatedAt",
            ExpressionAttributeNames={
                "#status": "status"
            },
            ExpressionAttributeValues={
                ":status": "inactive",
                ":updatedAt": now
            }
        )

        return response(True, "회원 탈퇴가 완료되었습니다.")

    except Exception as e:
        print("WithdrawUser Error:", e)
        return response(False, "서버 오류", error=str(e), status_code=500)



def verify_email(event, context):
    try:
        params = event.get("queryStringParameters") or {}
        token = params.get("token")

        if not token:
            return response(False, "인증 토큰이 필요합니다.", status_code=400)

        token_res = verification_table.get_item(Key={"token": token})
        token_item = token_res.get("Item")

        now = int(time.time())
        if not token_item or token_item.get("expiresAt", 0) < now:
            return response(False, "유효하지 않거나 만료된 토큰입니다.", status_code=400)

        user_id = token_item["userId"]

        users_table.update_item(
            Key={"userId": user_id},
            UpdateExpression="SET #status = :active, updatedAt = :updatedAt",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":active": "active", ":updatedAt": now}
        )

        verification_table.delete_item(Key={"token": token})

        return response(True, "이메일 인증이 완료되었습니다.")

    except Exception as e:
        print("VerifyEmail Error:", e)
        return response(False, "서버 오류", error=str(e), status_code=500)

# 인증 이메일 전송 함수
def send_verification_email(user_id, email):
    token = str(uuid.uuid4())
    now = int(time.time())
    expires_at = now + 86400  # 24시간

    verification_table.put_item(Item={
        "token": token,
        "userId": user_id,
        "createdAt": now,
        "expiresAt": expires_at
    })

    verification_link = f"{BASE_URL}?token={token}"
    subject = "Lexora 이메일 인증 안내"
    body_text = f"""Lexora를 이용해주셔서 감사합니다.

이메일 인증을 위해 아래 링크를 클릭해주세요:

{verification_link}

이 링크는 24시간 동안 유효합니다.
"""
    body_html = f"""
    <html>
      <head></head>
      <body>
        <h3>Lexora 이메일 인증</h3>
        <p><a href="{verification_link}">여기를 클릭하여 인증하세요</a></p>
        <p>또는 아래 URL을 복사해서 브라우저에 붙여넣기 해주세요:</p>
        <p>{verification_link}</p>
        <hr/>
        <p>링크는 24시간 후 만료됩니다.</p>
      </body>
    </html>
    """

    try:
        ses_client.send_email(
            Source=EMAIL_SENDER,
            Destination={"ToAddresses": [email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"}
                }
            }
        )
    except Exception as e:
        print("SES 발송 오류:", e)
        # TODO : 필요시 재시도 로직 또는 fallback 추가

def resend_verification(event, context):
    try:
        body = json.loads(event["body"])
        email = body.get("email")

        if not email:
            return response(False, "이메일을 입력하세요.", status_code=400)

        if not is_valid_email(email):
            return response(False, "유효하지 않은 이메일 형식입니다.", status_code=400)

        # 사용자 조회
        result = users_table.query(
            IndexName="email-index",
            KeyConditionExpression="email = :e",
            ExpressionAttributeValues={":e": email}
        )

        if result["Count"] == 0:
            return response(False, "해당 이메일로 가입된 사용자를 찾을 수 없습니다.", status_code=404)

        user = result["Items"][0]

        if user.get("status") == "active":
            return response(False, "이미 이메일 인증이 완료된 계정입니다.", status_code=409)

        send_verification_email(user["userId"], email)

        return response(True, "인증 메일이 다시 전송되었습니다.")

    except Exception as e:
        print("ResendVerification Error:", e)
        return response(False, "서버 오류", error=str(e), status_code=500)

def change_password(event, context):
    try:
        headers = event.get("headers", {})
        session_id = headers.get("Authorization")

        if not session_id:
            return response(False, "세션이 필요합니다.", status_code=401)

        session_res = sessions_table.get_item(Key={"sessionId": session_id})
        session = session_res.get("Item")
        now = int(time.time())
        if not session or not session.get("isValid", False) or session.get("expiresAt", 0) < now:
            return response(False, "유효하지 않은 세션입니다.", status_code=401)

        user_id = session["userId"]

        body = json.loads(event["body"])
        current_password = body.get("currentPassword")
        new_password = body.get("newPassword")

        if not current_password or not new_password:
            return response(False, "현재 비밀번호와 새 비밀번호를 입력하세요.", status_code=400)

        if len(new_password) < 8:
            return response(False, "비밀번호는 8자 이상이어야 합니다.", status_code=400)

        user_res = users_table.get_item(Key={"userId": user_id})
        user = user_res.get("Item")

        if not user:
            return response(False, "사용자를 찾을 수 없습니다.", status_code=404)

        if hash_password(current_password) != user["passwordHash"]:
            return response(False, "현재 비밀번호가 일치하지 않습니다.", status_code=401)

        if hash_password(new_password) == user["passwordHash"]:
            return response(False, "새 비밀번호는 현재 비밀번호와 달라야 합니다.", status_code=400)

        users_table.update_item(
            Key={"userId": user_id},
            UpdateExpression="SET passwordHash = :newHash, updatedAt = :updatedAt",
            ExpressionAttributeValues={
                ":newHash": hash_password(new_password),
                ":updatedAt": now
            }
        )

        return response(True, "비밀번호가 성공적으로 변경되었습니다.")

    except Exception as e:
        print("ChangePassword Error:", e)
        return response(False, "서버 오류", error=str(e), status_code=500)

def modify_email(event, context):
    try:
        headers = event.get("headers", {})
        session_id = headers.get("Authorization")

        if not session_id:
            return response(False, "세션이 필요합니다.", status_code=401)

        session = sessions_table.get_item(Key={"sessionId": session_id}).get("Item")
        now = int(time.time())
        if not session or not session.get("isValid") or session.get("expiresAt", 0) < now:
            return response(False, "유효하지 않은 세션입니다.", status_code=401)

        user_id = session["userId"]
        user_res = users_table.get_item(Key={"userId": user_id})
        user = user_res.get("Item")
        if not user:
            return response(False, "사용자를 찾을 수 없습니다.", status_code=404)

        body = json.loads(event["body"])
        new_email = body.get("newEmail")
        password = body.get("password")

        if not new_email:
            return response(False, "이메일을 입력하세요.", status_code=400)
        if not is_valid_email(new_email):
            return response(False, "유효하지 않은 이메일 형식입니다.", status_code=400)
        if not password or hash_password(password) != user.get("passwordHash"):
            return response(False, "비밀번호가 일치하지 않습니다.", status_code=401)

        email_check = users_table.query(
            IndexName="email-index",
            KeyConditionExpression="email = :e",
            ExpressionAttributeValues={":e": new_email}
        )
        if email_check.get("Count") > 0:
            return response(False, "이미 등록된 이메일입니다.", status_code=409)

        users_table.update_item(
            Key={"userId": user_id},
            UpdateExpression="SET email = :email, #status = :unverified, updatedAt = :updatedAt",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":email": new_email, ":unverified": "unverified", ":updatedAt": now}

        )

        send_verification_email(user_id, new_email)
        return response(True, "이메일이 변경되었습니다. 인증 메일을 확인해 주세요.")

    except Exception as e:
        print("ModifyEmail Error:", e)
        return response(False, "서버 오류", error=str(e), status_code=500)

def example(event, context):
    return cors_response({
        "statusCode": 501,
        "body": json.dumps({"message": "본 함수는 테스트 용도 입니다."}, ensure_ascii=False)
    })



# Lambda 핸들러
def lambda_handler(event, context):
    print("Received event:", json.dumps(event))

    method = event.get("httpMethod", "").upper()
    path = event.get("path", "").lower()

    if method == "OPTIONS":
        return cors_response({
            "statusCode": 200,
            "body": json.dumps({"message": "CORS 프리플라이트 요청 성공"}, ensure_ascii=False)
        })

    if path.endswith("/register") and method == "POST":
        return register(event, context)
    elif path.endswith("/login") and method == "POST":
        return login(event, context)
    elif path.endswith("/me") and method == "GET":
        return get_me(event, context)
    elif path.endswith("/logout") and method == "POST":
        return logout(event, context)
    elif path.endswith("/modify") and method == "PUT":
        return modify_user(event, context)
    elif path.endswith("/withdraw") and method == "DELETE":
        return withdraw_user(event, context)
    elif path.endswith("/verify-email") and method == "GET":
        return verify_email(event, context)
    elif path.endswith("/resend-verification") and method == "POST":
        return resend_verification(event, context)
    elif path.endswith("/change-password") and method == "PUT":
        return change_password(event, context)
    elif path.endswith("/change-email") and method == "PUT":
        return modify_email(event, context)

    return cors_response({
        "statusCode": 404,
        "body": json.dumps({"message": "잘못된 경로입니다.", "path": path}, ensure_ascii=False)
    })
