from aws_cdk import (
    Stack,
    Duration,
    aws_s3 as s3,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_event_sources,
    aws_sqs as sqs,
    aws_iam as iam,
    aws_ecr_assets as ecr_assets,
    CfnOutput
)
from constructs import Construct


class LexoraDocConvpdfStack(Stack):
    def __init__(self, scope: Construct, construct_id: str,
                 raw_bucket_name: str = "lexora-raw-files-bucket",
                 converted_bucket_name: str = "lexora-converted-files-bucket",
                 files_table_name: str = "lexora-files",
                 versions_table_name: str = "lexora-file-versions",
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. 기존 S3 버킷 참조
        raw_bucket = s3.Bucket.from_bucket_name(self, "RawBucket", raw_bucket_name)
        converted_bucket = s3.Bucket.from_bucket_name(self, "ConvertedBucket", converted_bucket_name)

        # 2. 기존 SQS 큐 참조 (conv_queue: 입력, extract_queue: 다음 단계 출력)
        conv_queue = sqs.Queue.from_queue_attributes(
            self, "PreprocessQueue",
            queue_arn="arn:aws:sqs:ap-northeast-2:571600839644:LexoraPreprocessingStack-PreprocessQueueFC197E2A-31suvGB4KmWy",
            queue_url="https://sqs.ap-northeast-2.amazonaws.com/571600839644/LexoraPreprocessingStack-PreprocessQueueFC197E2A-31suvGB4KmWy"
        )

        extract_queue = sqs.Queue.from_queue_attributes(
            self, "ExtractQueue",
            queue_arn="arn:aws:sqs:ap-northeast-2:571600839644:LexoraDocExtractQueue",  
            queue_url="https://sqs.ap-northeast-2.amazonaws.com/571600839644/LexoraDocExtractQueue"
        )


        # 3. Lambda 함수 정의 (PDF 변환/복사 전용)
        conv_fn = _lambda.DockerImageFunction(
            self, "LexoraDocConvFunction",
            code=_lambda.DockerImageCode.from_image_asset(
                "lambdas/lexora_doc_convpdf",
                platform=ecr_assets.Platform.LINUX_AMD64
            ),
            timeout=Duration.minutes(10),
            memory_size=2048,
            environment={
                "RAW_BUCKET": raw_bucket.bucket_name,
                "CONVERTED_BUCKET": converted_bucket.bucket_name,
                "FILES_TABLE": files_table_name,
                "VERSIONS_TABLE": versions_table_name,
                "EXTRACT_QUEUE_URL": extract_queue.queue_url
            }
        )

        # 4. 권한 부여
        raw_bucket.grant_read(conv_fn)
        converted_bucket.grant_put(conv_fn)
        extract_queue.grant_send_messages(conv_fn)

        conv_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:UpdateItem", "dynamodb:PutItem"],
                resources=[
                    f"arn:aws:dynamodb:{self.region}:{self.account}:table/{files_table_name}",
                    f"arn:aws:dynamodb:{self.region}:{self.account}:table/{versions_table_name}"
                ]
            )
        )

        # 5. Lambda에 conv_queue 이벤트 소스 연결
        conv_fn.add_event_source(
            lambda_event_sources.SqsEventSource(
                conv_queue,
                batch_size=1
            )
        )

        # 6. 출력
        CfnOutput(self, "PreprocessQueueURL", value=conv_queue.queue_url)
        CfnOutput(self, "ConvLambdaName", value=conv_fn.function_name)
        CfnOutput(self, "ExtractQueueURL", value=extract_queue.queue_url)
