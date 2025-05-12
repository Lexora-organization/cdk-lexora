from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_event_sources,
    aws_sqs as sqs,
    aws_s3 as s3,
    aws_iam as iam,
    aws_ecr_assets as ecr_assets,
    CfnOutput
)
from aws_cdk.aws_lambda import Architecture, DockerImageCode, DockerImageFunction
from constructs import Construct

import boto3
from botocore.exceptions import ClientError


class LexoraDocExtractStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 converted_bucket_name: str = "lexora-converted-files-bucket",
                 files_table_name: str = "lexora-files",
                 account: str = "571600839644",
                 region: str = "ap-northeast-2",
                 **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # 버킷 참조
        converted_bucket = s3.Bucket.from_bucket_name(self, "ConvertedBucket", converted_bucket_name)

        extract_queue = sqs.Queue.from_queue_attributes(
            self, "ExtractQueue",
            queue_arn="arn:aws:sqs:ap-northeast-2:571600839644:LexoraDocExtractQueue",
            queue_url="https://sqs.ap-northeast-2.amazonaws.com/571600839644/LexoraDocExtractQueue"
        )

        embed_queue = sqs.Queue.from_queue_attributes(
            self, "EmbedQueue",
            queue_arn="arn:aws:sqs:ap-northeast-2:571600839644:LexoraDocEmbedQueue",
            queue_url="https://sqs.ap-northeast-2.amazonaws.com/571600839644/LexoraDocEmbedQueue"
        )

        # Lambda 정의
        extract_fn = _lambda.DockerImageFunction(
            self, "LexoraDocExtractFunction",
            code=_lambda.DockerImageCode.from_image_asset(
                "lambdas/lexora_doc_extract",
                platform=ecr_assets.Platform.LINUX_AMD64
            ),
            timeout=Duration.minutes(5),
            memory_size=2048,
            environment={
                "CONVERTED_BUCKET": converted_bucket.bucket_name,
                "EMBEDDING_QUEUE_URL": embed_queue.queue_url,
                "FILES_TABLE": files_table_name
            }
        )

        # 권한 부여
        converted_bucket.grant_read(extract_fn)
        embed_queue.grant_send_messages(extract_fn)

        extract_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:UpdateItem"],
                resources=[
                    f"arn:aws:dynamodb:{Stack.of(self).region}:{Stack.of(self).account}:table/{files_table_name}"
                ]
            )
        )

        # 이벤트 소스 연결
        extract_fn.add_event_source(
            lambda_event_sources.SqsEventSource(
                extract_queue,
                batch_size=1
            )
        )

        # 출력
        CfnOutput(self, "ExtractFunctionName", value=extract_fn.function_name)
        CfnOutput(self, "EmbedQueueURL", value=embed_queue.queue_url)
