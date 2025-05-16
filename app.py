#!/usr/bin/env python3
import aws_cdk as cdk

from cdk_lexora.lexora_users_stack import LexoraUsersStack
from cdk_lexora.lexora_doc_convpdf_stack import LexoraDocConvpdfStack
from cdk_lexora.lexora_doc_extract_stack import LexoraDocExtractStack
from cdk_lexora.lexora_doc_embed_stack import LexoraDocEmbedStack
from cdk_lexora.lexora_query_handler_stack import LexoraQueryHandlerStack
from cdk_lexora.lexora_query_session_handler_stack import LexoraQuerySessionHandlerStack

app = cdk.App()

# 공통 환경 변수
env = cdk.Environment(
    account="571600839644",
    region="ap-northeast-2",
)

# 공통 리소스 설정
files_table_name = "lexora-files"
user_sessions_table_name = "lexora-sessions"
query_sessions_table_name = "lexora-query-sessions"
opensearch_endpoint = "vpc-lexora-embed-index-mlbu2ea3gkp7l3fbphhabxpuje.ap-northeast-2.es.amazonaws.com"
opensearch_index = "lexora-doc-embed-v1"

# ① 사용자 관리 스택
LexoraUsersStack(app, "LexoraUsersStack", env=env)

# ② 문서 전처리(문서 비‑PDF/PDF 변환 및 저장) 스택
LexoraDocConvpdfStack(app, "LexoraDocConvpdfStack", env=env)

# ③ 텍스트 추출 + chunk 생성 스택
LexoraDocExtractStack(app, "LexoraDocExtractStack", env=env)

# ④ 임베딩 생성 + OpenSearch 저장 스택
LexoraDocEmbedStack(
    app,
    "LexoraDocEmbedStack",
    env=env,
    files_table_name=files_table_name,
    opensearch_endpoint=opensearch_endpoint,
    opensearch_index=opensearch_index
)

# ⑤ 질의 응답 세션 처리 스택
LexoraQueryHandlerStack(
    app,
    "LexoraQueryHandlerStack",
    env=env,
    files_table_name=files_table_name,
    query_sessions_table_name=query_sessions_table_name,
    opensearch_endpoint=opensearch_endpoint,
    opensearch_index=opensearch_index
)

# ⑥ 쿼리 세션 관리 (생성, 목록, 수정, 삭제 등)
LexoraQuerySessionHandlerStack(
    app,
    "LexoraQuerySessionHandlerStack",
    env=env,
    query_sessions_table_name=query_sessions_table_name,
    user_sessions_table_name=user_sessions_table_name  # 추가됨
)

app.synth()
