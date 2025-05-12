FROM public.ecr.aws/lambda/python:3.11

# 시스템 패키지 설치 (libcurl, OpenSSL 등 OpenSearch용)
RUN yum -y install gcc libcurl-devel openssl-devel

# 필요한 Python 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY handler.py ${LAMBDA_TASK_ROOT}

# 핸들러 설정
CMD ["handler.lambda_handler"]