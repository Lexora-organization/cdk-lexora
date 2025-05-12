# Lexora Document Embedding Lambda
FROM public.ecr.aws/lambda/python:3.11

# ---------- 파이썬 종속성 설치 ----------
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---------- Lambda 핸들러 코드 복사 ----------
COPY handler.py ${LAMBDA_TASK_ROOT}

# ---------- Lambda 실행 엔트리포인트 ----------
CMD ["handler.lambda_handler"]
