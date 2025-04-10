#!/usr/bin/env python3
import aws_cdk as cdk

from cdk_lexora.lexora_users_stack import LexoraUsersStack  # 경로 주의!

app = cdk.App()
LexoraUsersStack(app, "LexoraUsersStack", env=cdk.Environment(
    account="571600839644",
    region="ap-northeast-2"
))
app.synth()
