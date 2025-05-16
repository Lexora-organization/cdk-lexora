from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_ecr_assets as ecr_assets,
    CfnOutput
)
from aws_cdk.aws_lambda import DockerImageFunction, DockerImageCode
from constructs import Construct

class LexoraQuerySessionHandlerStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        query_sessions_table_name: str = "lexora-query-sessions",
        user_sessions_table_name: str = "lexora-user-sessions",  # 추가
        account: str = "571600839644",
        region: str = "ap-northeast-2",
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # Lambda 함수 정의
        session_fn = DockerImageFunction(
            self,
            "LexoraQuerySessionHandlerFunction",
            code=DockerImageCode.from_image_asset(
                "lambdas/lexora_query_session_handler",
                platform=ecr_assets.Platform.LINUX_AMD64,
            ),
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={
                "QUERY_SESSIONS_TABLE": query_sessions_table_name,
                "SESSIONS_TABLE": user_sessions_table_name  # 추가
            }
        )

        # API Gateway 연결
        api = apigateway.LambdaRestApi(
            self,
            "LexoraQuerySessionApi",
            handler=session_fn,
            proxy=True
        )

        # 권한 부여: 쿼리 세션 테이블 + 유저 세션 테이블
        session_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:Scan",
                ],
                resources=[
                    f"arn:aws:dynamodb:{region}:{account}:table/{query_sessions_table_name}",
                    f"arn:aws:dynamodb:{region}:{account}:table/{user_sessions_table_name}",  # 추가
                ]
            )
        )

        # 출력
        CfnOutput(self, "QuerySessionApiUrl", value=api.url)
        CfnOutput(self, "QuerySessionFunctionName", value=session_fn.function_name)
