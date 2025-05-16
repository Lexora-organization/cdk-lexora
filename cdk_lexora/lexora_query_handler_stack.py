from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_event_sources,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
    CfnOutput,
)
from aws_cdk.aws_lambda import DockerImageFunction, DockerImageCode
from constructs import Construct


class LexoraQueryHandlerStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        files_table_name: str = "lexora-files",
        query_sessions_table_name: str = "lexora-query-sessions",
        account: str = "571600839644",
        region: str = "ap-northeast-2",
        opensearch_endpoint: str = "vpc-lexora-embed-index-mlbu2ea3gkp7l3fbphhabxpuje.ap-northeast-2.es.amazonaws.com",
        opensearch_index: str = "lexora-doc-embed-v1",
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        # === VPC 및 서브넷 설정 ===
        vpc = ec2.Vpc.from_lookup(self, "LexoraVpc", vpc_id="vpc-0f5a1cf92cb7762da")
        opensearch_sg = ec2.SecurityGroup.from_security_group_id(
            self, "LexoraDefaultSG", "sg-0e325a0ed63647e79"
        )

        private_subnets = [
            ec2.Subnet.from_subnet_id(self, "SubnetA", "subnet-00d96d1f415499e3a"),
            ec2.Subnet.from_subnet_id(self, "SubnetB", "subnet-04cea4b1f7054cdd0"),
            ec2.Subnet.from_subnet_id(self, "SubnetC", "subnet-0697bc8321ff2d2d0"),
        ]

        # === Lambda 함수 생성 ===
        query_fn = DockerImageFunction(
            self,
            "LexoraQueryHandlerFunction",
            code=DockerImageCode.from_image_asset(
                "lambdas/lexora_query_handler",
                platform=ecr_assets.Platform.LINUX_AMD64,
            ),
            timeout=Duration.seconds(30),
            memory_size=1024,
            environment={
                "FILES_TABLE": files_table_name,
                "QUERY_SESSIONS_TABLE": query_sessions_table_name,
                "BEDROCK_REGION": region,
                "OPENSEARCH_ENDPOINT": opensearch_endpoint,
                "OPENSEARCH_INDEX": opensearch_index,
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnets=private_subnets),
            security_groups=[opensearch_sg],
            allow_public_subnet=True
        )

        # === API Gateway 생성 ===
        api = apigateway.LambdaRestApi(
            self,
            "LexoraQueryApi",
            handler=query_fn,
            proxy=True  # or False + method/resource 수동 정의
        )

        # === Lambda 권한 설정 ===
        query_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                ],
                resources=[
                    f"arn:aws:dynamodb:{region}:{account}:table/{files_table_name}",
                    f"arn:aws:dynamodb:{region}:{account}:table/{query_sessions_table_name}",
                ],
            )
        )

        query_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream"
                ],
                resources=["*"]  # ← 여기가 모든 모델 사용 허용
            )
        )




        query_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem"],
                resources=[
                    f"arn:aws:dynamodb:{region}:{account}:table/lexora-sessions"
                ]
            )
        )


        query_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["es:ESHttpGet", "es:ESHttpPost"],
                resources=[
                    f"arn:aws:es:{region}:{account}:domain/lexora-embed-index/*"
                ],
            )
        )

        # === 출력 ===
        CfnOutput(self, "QueryApiUrl", value=api.url)
        CfnOutput(self, "QueryFunctionName", value=query_fn.function_name)

