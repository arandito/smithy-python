# aws-credentials-imds

Provides an IMDSv2 metadata client and EC2 instance metadata credential
resolver. Installing the package adds the `EC2_INSTANCE_METADATA` source to the
modular AWS credential chain.

```python
from aws_credentials_imds import IMDSConfig, IMDSCredentialsResolver
from smithy_http.aio.aiohttp import AIOHTTPClient

resolver = IMDSCredentialsResolver(
    http_client=AIOHTTPClient(),
    config=IMDSConfig(endpoint_mode="IPv6"),
)
credentials = await resolver.get_identity(properties={})
```

The modular provider resolves IMDS endpoint, endpoint mode, disabled state, and
instance profile name settings from the environment and active shared profile.
Remaining IMDS Client and IMDS Credentials Provider v2 behavior will be added
in a follow-up implementation.
