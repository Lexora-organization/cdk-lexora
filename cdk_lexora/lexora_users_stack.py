from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_apigateway as apigw,
)
from constructs import Construct

class LexoraUsersStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        # Lambda 함수 생성
        self.lexora_users_lambda = _lambda.Function(
            self, "LexoraUsersFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("lambdas/lexora_users"),
            timeout=Duration.seconds(30),
            environment={
                "EMAIL_SENDER": "lexora02095@gmail.com",
                "EMAIL_VERIFY_URL": "https://lexora.ai/verify-email",
                "SALT_KEY": "your-default-salt"
            }
        )

        # IAM 권한 부여
        self.lexora_users_lambda.add_to_role_policy(iam.PolicyStatement(
            actions=[
                "dynamodb:*",
                "ses:SendEmail",
                "ses:SendRawEmail"
            ],
            resources=["*"]  # 보안을 위해 나중에 특정 리소스로 좁히기 추천
        ))

        # API Gateway 설정
        api = apigw.RestApi(self, "LexoraUsersAPI",
            rest_api_name="Lexora Users Service",
            deploy_options=apigw.StageOptions(stage_name="default")
        )

        # /lexora-users 엔드포인트 생성
        users = api.root.add_resource("lexora-users")

        # 각 API 경로 설정
        users.add_resource("register").add_method("POST", apigw.LambdaIntegration(self.lexora_users_lambda))
        users.add_resource("login").add_method("POST", apigw.LambdaIntegration(self.lexora_users_lambda))
        users.add_resource("me").add_method("GET", apigw.LambdaIntegration(self.lexora_users_lambda))
        users.add_resource("logout").add_method("POST", apigw.LambdaIntegration(self.lexora_users_lambda))
        users.add_resource("modify").add_method("PUT", apigw.LambdaIntegration(self.lexora_users_lambda))
        users.add_resource("withdraw").add_method("DELETE", apigw.LambdaIntegration(self.lexora_users_lambda))
        users.add_resource("verify-email").add_method("GET", apigw.LambdaIntegration(self.lexora_users_lambda))
        users.add_resource("resend-verification").add_method("POST", apigw.LambdaIntegration(self.lexora_users_lambda))
        users.add_resource("change-password").add_method("PUT", apigw.LambdaIntegration(self.lexora_users_lambda))
        users.add_resource("change-email").add_method("PUT", apigw.LambdaIntegration(self.lexora_users_lambda))
