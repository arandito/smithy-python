# AWS Credentials STS

STS-backed AWS credential resolvers for Smithy Python.

Installing this package adds the `ProfileAssumeRole` provider to the modular
AWS credential chain. `AssumeRoleCredentialsResolver` can also be configured
directly with any AWS credentials resolver:

```python
from aws_credentials_sts import AssumeRoleCredentialsResolver

resolver = AssumeRoleCredentialsResolver(
    source_resolver=source_resolver,
    role_arn="arn:aws:iam::123456789012:role/example",
)
```
