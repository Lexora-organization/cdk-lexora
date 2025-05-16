순번	처리 단계	Lambda 함수 이름 제안	설명
1	[문서 업로드]	lexora-file	사용자 앱에서 S3에 직접 업로드 (Lambda는 없음)  

file_notify_upload_complete -> send_to_preprocess_queue -> LexoraPreprocessingStack-PreprocessQueueFC197E2A-31suvGB4KmWy queue 에 전송

LexoraPreprocessingStack-PreprocessQueueFC197E2A-31suvGB4KmWy -> lexora-doc-convpdf 람다함수 실행 pdf변환

2	[PDF 변환]	lexora-doc-convpdf	.docx → .pdf 변환 (LibreOffice 사용)
아래와 같은 구조로 저장이 됨 
s3://lexora-converted-files-bucket/userId/yyyy/mm/dd/fileid.pdf 
s3://lexora-converted-files-bucket/4b631cdf-a312-44e5-87a0-f3048f0fa013/2025/04/30/0ce15d69-725b-4160-a0c5-26a360aabdd3.pdf

3	[텍스트 추출]	lexora-doc-extract (동일)	pdfplumber로 PDF에서 텍스트 추출
4	[chunk 생성]	lexora-doc-extract (동일)	추출된 텍스트를 문단/길이 기준으로 나누어 chunk 생성

extract queue-> processing -> EmbedQueue

5	[임베딩 생성]	lexora-doc-embed	Bedrock Titan 등으로 각 chunk 임베딩 처리
6	[벡터 저장]	lexora-doc-embed	벡터와 메타데이터를 OpenSearch에 저장

############################################################

todo userId 매핑이 필요한가? -> 필요하다면 opensearch 대시보드 다시 들어가야함 -> 중지된 인스턴스 살리고 


❯ ssh -i lexora-test.pem ec2-user@52.78.228.244
❯ ssh -i lexora-test.pem -N -L 5601:vpc-lexora-embed-index-mlbu2ea3gkp7l3fbphhabxpuje.ap-northeast-2.es.amazonaws.com:443 ec2-user@52.78.228.244

으로 진입 가능하다. admin !Qwe784578로 들어갈 수 있음 


############################################################

lexora-embed-index opensearch 정보

admin
!Qwe784578

삭제
작업
일반 정보
이름
lexora-embed-index
도메인 ARN
arn:aws:es:ap-northeast-2:571600839644:domain/lexora-embed-index
배포 옵션
3-대기 상태인 AZ
Domain processing status  정보
활성
구성 변경 상태 정보
변경 사항 적용 중

ID 변경
4ce6c659-958c-4de4-b4d2-ccc674f86298
클러스터 상태 정보
-
버전 정보
OpenSearch 2.19 (최신)
서비스 소프트웨어 버전 정보
OpenSearch_2_19_R20250428 (최신)
OpenSearch 대시보드 URL(IPv4)
https://vpc-lexora-embed-index-mlbu2ea3gkp7l3fbphhabxpuje.ap-northeast-2.es.amazonaws.com/_dashboards 
도메인 엔드포인트(VPC)
https://vpc-lexora-embed-index-mlbu2ea3gkp7l3fbphhabxpuje.ap-northeast-2.es.amazonaws.com


7	[AI 질의 응답]	lexora-query-handler (또는 lexora-doc-query)	사용자의 질문을 받아 relevant chunk 검색 후 LLM 호출
✅ 보조 리소스 이름 예시 (테이블, 버킷 등)

리소스	이름 예시	설명
S3 (원본 업로드)	lexora-raw-files-bucket	.docx, .pdf, .pptx 저장
S3 (PDF 저장)	lexora-converted-files-bucket	변환된 .pdf 저장
DynamoDB (chunk 저장)	lexora-doc-chunks	fileId, chunkIndex, text, ownerId 등
OpenSearch Index	lexora-doc-embeddings	kNN 기반 chunk 검색용
질문/답변 API	POST /query-docs	fileId[] + question 받아 응답 생성
✅ 전체 구성 요약 (Lambda 중심)
plaintext
복사
편집
1. S3 업로드
   ↓
2. Lambda: lexora-doc-extract
   - 변환(.docx→.pdf)
   - 텍스트 추출
   - chunk 생성
   - chunk 저장 (DynamoDB)
   - SQS → lexora-doc-embed
   ↓
3. Lambda: lexora-doc-embed
   - chunk 조회
   - Bedrock 임베딩
   - SQS → lexora-doc-index
   ↓
4. Lambda: lexora-doc-index
   - OpenSearch 벡터 저장
   ↓
5. Lambda/API: lexora-query-handler
   - fileId 기준 검색
   - Bedrock 호출 → 응답 생성


1. lexora-doc-extract
   → chunk 저장 (DynamoDB)
   → SQS 메시지 전송 (fileId, ownerId)

2. lexora-doc-embed
   → fileId로 chunk 조회 (DynamoDB)
   → 각 chunk를 Bedrock Titan 등으로 임베딩
   → SQS 메시지 전송 (fileId, chunkIndex, text, embedding 등)

3. lexora-doc-index
   → 위 메시지 수신 후 OpenSearch에 저장




curl -X POST https://5txrsesstc.execute-api.ap-northeast-2.amazonaws.com/prod/query \
  -H "Content-Type: application/json" \
  -H "Authorization: 8d1548b1-1bc5-46de-b0fa-1c60e7ac99d9" \
  -d '{
        "prompt": "언제까지 신청가능한가요?",
        "fileIds": ["71d31ed8-7cec-48e7-89dd-d91e6c06f71a"]
      }'



aws dynamodb get-item \
  --table-name lexora-sessions \
  --key '{"sessionId": {"S": "8d1548b1-1bc5-46de-b0fa-1c60e7ac99d9"}}'


curl -X GET https://897kpvtaa0.execute-api.ap-northeast-2.amazonaws.com/default/lexora-users/me \
  -H "Authorization: 8d1548b1-1bc5-46de-b0fa-1c60e7ac99d9"

❯ curl -X POST https://5txrsesstc.execute-api.ap-northeast-2.amazonaws.com/prod/query \
  -H "Content-Type: application/json" \
  -H "Authorization: 8d1548b1-1bc5-46de-b0fa-1c60e7ac99d9" \
  -d '{
        "prompt": "가산점내용 알려줘",
        "fileIds": ["71d31ed8-7cec-48e7-89dd-d91e6c06f71a"]
      }'


curl -X GET "https://lzh1iiwotb.execute-api.ap-northeast-2.amazonaws.com/default/lexora-file/get-file-metadata?fileId=71d31ed8-7cec-48e7-89dd-d91e6c06f71a" \
  -H "Authorization: 8d1548b1-1bc5-46de-b0fa-1c60e7ac99d9"



❯ curl -X POST https://5txrsesstc.execute-api.ap-northeast-2.amazonaws.com/prod/query \
  -H "Content-Type: application/json" \
  -H "Authorization: 603f3a5d-ba25-4597-8a3e-7999c5bae8c6" \
  -d '{
        "prompt": "문서내용 요약해",
        "fileIds": ["1edb4f8d-93ff-43ac-ba49-080028a7af32"]
      }'

❯ curl -X POST https://5txrsesstc.execute-api.ap-northeast-2.amazonaws.com/prod/generate_query \
  -H "Content-Type: application/json" \
  -H "Authorization: 603f3a5d-ba25-4597-8a3e-7999c5bae8c6" \
  -d '{
        "fileIds": ["1edb4f8d-93ff-43ac-ba49-080028a7af32"]
      }'




curl -X POST https://y0mqvx0h5e.execute-api.ap-northeast-2.amazonaws.com/prod/query-session \
  -H "Authorization: 74ee6d43-5a77-4295-897d-2a1bb6842fda" \
  -H "Content-Type: application/json" \
  -d '{"sessionTitle": "나의 새 질의 세션"}'

curl -X GET https://y0mqvx0h5e.execute-api.ap-northeast-2.amazonaws.com/prod/query-session \
  -H "Authorization: 74ee6d43-5a77-4295-897d-2a1bb6842fda"



순번	처리 단계	Lambda 함수 이름 제안	설명
1	[문서 업로드]	lexora-file	사용자 앱에서 S3에 직접 업로드 

file_notify_upload_complete -> send_to_preprocess_queue -> LexoraPreprocessingStack-PreprocessQueueFC197E2A-31suvGB4KmWy queue 에 전송

LexoraPreprocessingStack-PreprocessQueueFC197E2A-31suvGB4KmWy -> lexora-doc-convpdf 람다함수 실행 pdf변환

2	[PDF 변환]	lexora-doc-convpdf	.docx → .pdf 변환 (LibreOffice 사용)
아래와 같은 구조로 저장이 됨 
s3://lexora-converted-files-bucket/userId/yyyy/mm/dd/fileid.pdf 
s3://lexora-converted-files-bucket/4b631cdf-a312-44e5-87a0-f3048f0fa013/2025/04/30/0ce15d69-725b-4160-a0c5-26a360aabdd3.pdf

3	[텍스트 추출]	lexora-doc-extract (동일)	pdfplumber로 PDF에서 텍스트 추출
4	[chunk 생성]	lexora-doc-extract (동일)	추출된 텍스트를 문단/길이 기준으로 나누어 chunk 생성

extract queue-> processing -> EmbedQueue

5	[임베딩 생성]	lexora-doc-embed	Bedrock Titan 등으로 각 chunk 임베딩 처리
6	[벡터 저장]	lexora-doc-embed	벡터와 메타데이터를 OpenSearch에 저장

7	[AI 질의 응답]	lexora-query-handler (또는 lexora-doc-query)	사용자의 질의를 받으면 대답을 함, query바탕으로 제목을 생성함, 기본 file을 바탕으로 추천질의 질문 생성
8 [querysession 핸들러] lexora-query-session-handler query세션에 대해 생성 조회 이름변경 삭제등 지원




curl -X POST https://5txrsesstc.execute-api.ap-northeast-2.amazonaws.com/prod/generate_query \
  -H "Content-Type: application/json" \
  -H "Authorization: 74ee6d43-5a77-4295-897d-2a1bb6842fda" \
  -d '{
        "fileIds": ["1edb4f8d-93ff-43ac-ba49-080028a7af32"]
      }'


curl -X POST https://y0mqvx0h5e.execute-api.ap-northeast-2.amazonaws.com/prod/query \
  -H "Authorization: 74ee6d43-5a77-4295-897d-2a1bb6842fda" \
  -H "Content-Type: application/json" \
  -d '{
    "querySessionId": "4cc490c6-7c15-4a1d-8fac-41b4f5bcef99",
    "prompt": "AI 모델이 생겨난 배경이 무엇인가요?"
  }'



curl -X POST https://5txrsesstc.execute-api.ap-northeast-2.amazonaws.com/prod/query \
  -H "Authorization: 74ee6d43-5a77-4295-897d-2a1bb6842fda" \
  -H "Content-Type: application/json" \
  -d '{
    "querySessionId": "4cc490c6-7c15-4a1d-8fac-41b4f5bcef99",
    "prompt": "지원 요건이 어떻게 되나요?",
    "fileIds": ["1edb4f8d-93ff-43ac-ba49-080028a7af32"]
  }'
