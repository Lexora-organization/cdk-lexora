# Lexora Document Preprocessing Lambda
FROM public.ecr.aws/lambda/python:3.11

# ---------- LibreOffice 7.5.9.2 설치 ----------
ARG LO_VERSION=7.5.9.2
RUN set -e; \
    BASE="https://downloadarchive.documentfoundation.org/libreoffice/old/${LO_VERSION}/rpm/x86_64"; \
    FILE="LibreOffice_${LO_VERSION}_Linux_x86-64_rpm.tar.gz"; \
    curl -Lsf "${BASE}/${FILE}" -o /tmp/lo.tar.gz; \
    yum -y install \
        fontconfig \
        gzip \
        tar \
        glib2 \
        libXinerama \
        libXrandr \
        libXcursor \
        libXext \
        libXfixes \
        libXrender \
        libSM \
        libX11 \
        libXau \
        libxcb \
        dbus-libs \
        java-1.8.0-openjdk-headless \
        cairo; \
    tar -xzf /tmp/lo.tar.gz -C /tmp; \
    yum -y localinstall /tmp/LibreOffice_*/RPMS/*.rpm; \
    rm -rf /tmp/lo.tar.gz /tmp/LibreOffice_*; \
    yum -y clean all && rm -rf /var/cache/yum

# ---------- libreoffice 명령어 등록 ----------
RUN LIBRE_BIN=$(find /opt -name soffice | grep /program/soffice | head -n1) && \
    echo "LibreOffice found at: $LIBRE_BIN" && \
    ln -s "$LIBRE_BIN" /usr/bin/libreoffice

# ---------- 한글 폰트 복사 ----------
RUN mkdir -p /usr/share/fonts/extra
COPY NanumGothicCoding-2.5/*.ttf /usr/share/fonts/extra/
RUN fc-cache -fv

# ---------- 파이썬 종속성 설치 ----------
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---------- Lambda 핸들러 코드 복사 ----------
COPY handler.py ${LAMBDA_TASK_ROOT}

# ---------- Lambda 실행 엔트리포인트 ----------
CMD ["handler.lambda_handler"]
