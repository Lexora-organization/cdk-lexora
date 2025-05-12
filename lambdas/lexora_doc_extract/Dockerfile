# Lambda용 Python 3.11 이미지
FROM public.ecr.aws/lambda/python:3.11

# 시스템 패키지 설치 (pdfplumber 의존)
RUN yum -y install \
    gcc \
    cairo \
    cairo-devel \
    libjpeg \
    libpng \
    freetype \
    poppler-utils \
    && yum clean all && rm -rf /var/cache/yum

# 파이썬 종속성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Lambda 핸들러 복사
COPY handler.py ${LAMBDA_TASK_ROOT}

# Lambda 엔트리포인트 지정
CMD ["handler.lambda_handler"]
