from aws_cdk import Stack, aws_lambda as _lambda
from constructs import Construct

class LexoraUsersStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        self.lexora_users_lambda = _lambda.Function.from_function_arn(
            self, "LexoraUsersLambda",
            function_arn="arn:aws:lambda:ap-northeast-2:571600839644:function:lexora-users"
        )
