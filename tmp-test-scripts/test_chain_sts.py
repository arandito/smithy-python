import asyncio

from aws_sdk_sts.client import AsyncSTSClient
from aws_sdk_sts.config import Config
from aws_sdk_sts.models import GetCallerIdentityInput
from smithy_aws_core.identity import IdentityChain, AWSCredentialsIdentity


async def main():
    client = AsyncSTSClient(
        config=Config(
            endpoint_uri="https://sts.us-west-2.amazonaws.com",
            region="us-west-2",
            aws_credentials_identity_resolver=await IdentityChain.create(
                identity_type=AWSCredentialsIdentity,
            ),
        )
    )
    response = await client.get_caller_identity(GetCallerIdentityInput())

    print(response)


asyncio.run(main())
