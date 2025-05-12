[1] 문서 업로드 (PDF 또는 변환 필요 포맷)
     ↓
[2] Lambda: lexora-doc-extract
     - PDF 변환 (LibreOffice)
     - 텍스트 추출 (pdfplumber)
     - 문단 chunk 생성
     - chunk → DynamoDB 저장
     - ✅ SQS 전송 (EMBED_QUEUE_URL)

[3] Lambda: lexora-doc-embed
     - chunk 조회
     - Amazon Bedrock Embedding 호출
     - ✅ embedding 결과 → SQS 또는 내부 처리로 lexora-doc-index로 전달

[4] Lambda: lexora-doc-index
     - OpenSearch 저장 (fileId 필터링 가능)