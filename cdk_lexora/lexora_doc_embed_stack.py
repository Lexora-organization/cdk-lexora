from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_event_sources,
    aws_sqs as sqs,
    aws_iam as iam,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
    CfnOutput,
)
from aws_cdk.aws_lambda import DockerImageFunction, DockerImageCode
from constructs import Construct


class LexoraDocEmbedStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        files_table_name: str = "lexora-files",
        account: str = "571600839644",
        region: str = "ap-northeast-2",
        opensearch_endpoint: str = "vpc-lexora-embed-index-mlbu2ea3gkp7l3fbphhabxpuje.ap-northeast-2.es.amazonaws.com",
        opensearch_index: str = "lexora-doc-embed-v1",
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)

        
        # 0. VPC + Subnet 지정
        vpc = ec2.Vpc.from_lookup(self, "LexoraVpc", vpc_id="vpc-0f5a1cf92cb7762da")
        
        opensearch_sg = ec2.SecurityGroup.from_security_group_id(
            self, "LexoraDefaultSG", "sg-0e325a0ed63647e79"
        )

        private_subnets = [
            ec2.Subnet.from_subnet_id(self, "LexoraPrivateSubnetA", "subnet-00d96d1f415499e3a"),
            ec2.Subnet.from_subnet_id(self, "LexoraPrivateSubnetB", "subnet-04cea4b1f7054cdd0"),
            ec2.Subnet.from_subnet_id(self, "LexoraPrivateSubnetC", "subnet-0697bc8321ff2d2d0"),
        ]
                
        # 1. SQS 큐 참조 (이미 생성된 큐 사용)
        embed_queue = sqs.Queue.from_queue_attributes(
            self,
            "EmbedQueue",
            queue_arn=f"arn:aws:sqs:{region}:{account}:LexoraDocEmbedQueue",
            queue_url=f"https://sqs.{region}.amazonaws.com/{account}/LexoraDocEmbedQueue",
        )

        # 2. Lambda 함수 생성 (Docker 이미지 기반, VPC 연결 포함, 프라이빗 서브넷으로 변경)
        embed_fn = DockerImageFunction(
            self,
            "LexoraDocEmbedFunction",
            code=DockerImageCode.from_image_asset(
                "lambdas/lexora_doc_embed",
                platform=ecr_assets.Platform.LINUX_AMD64,
            ),
            timeout=Duration.minutes(3),
            memory_size=2048,
            environment={
                "FILES_TABLE": files_table_name,
                "BEDROCK_REGION": region,
                "OPENSEARCH_ENDPOINT": opensearch_endpoint.replace("https://", ""),
                "OPENSEARCH_INDEX": opensearch_index,
            },
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnets=private_subnets
            ),
            security_groups=[opensearch_sg],
            allow_public_subnet=True
        )

        # 3. SQS 메시지 소비 권한
        embed_queue.grant_consume_messages(embed_fn)

        # 4. DynamoDB 업데이트 권한
        embed_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:UpdateItem"],
                resources=[f"arn:aws:dynamodb:{region}:{account}:table/{files_table_name}"],
            )
        )

        # 5. Bedrock 호출 권한
        embed_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[f"arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"],
            )
        )

        # 6. OpenSearch 호출 권한
        embed_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["es:ESHttpPost", "es:ESHttpPut", "es:ESHttpGet"],
                resources=[f"arn:aws:es:{region}:{account}:domain/lexora-embed-index/*"],
            )
        )

        # 7. SQS 이벤트 소스 등록
        embed_fn.add_event_source(
            lambda_event_sources.SqsEventSource(embed_queue, batch_size=1)
        )

        # 8. 출력
        CfnOutput(self, "EmbedFunctionName", value=embed_fn.function_name)
        CfnOutput(self, "EmbedQueueURL", value=embed_queue.queue_url)
