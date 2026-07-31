import asyncio

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient
from aws_sdk_bedrock_runtime.config import Config
from aws_sdk_bedrock_runtime.models import ContentBlockText, ConverseInput, Message
from smithy_aws_core.identity import IdentityChain, AWSCredentialsIdentity
from aws_credentials_sts import ProfileAssumeRoleCredentialsResolver
from smithy_aws_core.config import load_config
import logging


# logging.basicConfig(level=logging.DEBUG)


async def main():
    config = await load_config()
    client = BedrockRuntimeClient(
        config=Config(
            endpoint_uri="https://bedrock-runtime.us-west-2.amazonaws.com",
            region="us-west-2",
            aws_credentials_identity_resolver=ProfileAssumeRoleCredentialsResolver(profile_name="default", profile_file=config)
        )
    )
    response = await client.converse(
        ConverseInput(
            model_id="us.anthropic.claude-sonnet-4-6",
            messages=[
                Message(
                    role="user",
                    content=[ContentBlockText(value="Say hello in one sentence.")],
                )
            ],
        )
    )
    print(response)


asyncio.run(main())
