# aws-credentials-http

Provides the container HTTP credential client and resolver for AWS SDKs.
Installing the package adds the `ECS_CONTAINER` source to the modular AWS
credential chain.

```python
from aws_credentials_http import ContainerCredentialsResolver
from smithy_http.aio.aiohttp import AIOHTTPClient

resolver = ContainerCredentialsResolver(http_client=AIOHTTPClient())
credentials = await resolver.get_identity(properties={})
```

General-purpose HTTP endpoint support will be added in a follow-up
implementation of the General HTTP Credentials Provider SEP.
