import os

import pytest
from moto import mock_aws

# Dummy credentials/region so boto3 never touches real AWS, even if this
# machine has real AWS credentials configured ambiently.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")


@pytest.fixture(scope="session", autouse=True)
def aws_mock():
    """moto is the real-instance substitute here -- see README's Testing section
    for why (AWS IoT Core has no free local emulator; LocalStack's IoT support
    requires a paid plan)."""
    with mock_aws():
        yield
