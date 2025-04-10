#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.lexora_users_stack import LexoraUsersStack

app = cdk.App()
LexoraUsersStack(app, "LexoraUsersStack", env=cdk.Environment(
    region="ap-northeast-2", account="571600839644"
))
app.synth()
