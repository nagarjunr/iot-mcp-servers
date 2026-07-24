import uuid

import pytest

import awsiotcoremcpserver as server

THING_NAME = "pytest-job-thing"


@pytest.fixture(autouse=True)
def seed_thing():
    server.create_thing(THING_NAME, overwrite=True)
    yield
    server.client.delete_thing(thingName=THING_NAME)


def _thing_arn() -> str:
    return server.get_thing(THING_NAME)["thingArn"]


def test_create_and_get_job():
    job_id = f"pytest-job-{uuid.uuid4().hex[:8]}"
    result = server.create_job(job_id, thing_arns=[_thing_arn()], document={"operation": "reboot"})
    assert result["jobId"] == job_id

    fetched = server.get_job(job_id)
    assert fetched["job"]["jobId"] == job_id

    server.delete_job(job_id, confirm=True, force=True)


def test_list_jobs_includes_created_job():
    job_id = f"pytest-job-{uuid.uuid4().hex[:8]}"
    server.create_job(job_id, thing_arns=[_thing_arn()], document={"operation": "noop"})

    ids = {j["jobId"] for j in server.list_jobs()["jobs"]}
    assert job_id in ids

    server.delete_job(job_id, confirm=True, force=True)


def test_cancel_job_requires_confirm():
    job_id = f"pytest-job-{uuid.uuid4().hex[:8]}"
    server.create_job(job_id, thing_arns=[_thing_arn()], document={"operation": "noop"})

    with pytest.raises(ValueError, match="confirm"):
        server.cancel_job(job_id)
    result = server.cancel_job(job_id, confirm=True)
    assert result["canceled"] is True

    server.delete_job(job_id, confirm=True, force=True)


def test_delete_job_requires_confirm():
    job_id = f"pytest-job-{uuid.uuid4().hex[:8]}"
    server.create_job(job_id, thing_arns=[_thing_arn()], document={"operation": "noop"})

    with pytest.raises(ValueError, match="confirm"):
        server.delete_job(job_id)
    result = server.delete_job(job_id, confirm=True, force=True)
    assert result["deleted"] is True


def test_list_job_executions_for_job_and_thing():
    job_id = f"pytest-job-{uuid.uuid4().hex[:8]}"
    server.create_job(job_id, thing_arns=[_thing_arn()], document={"operation": "noop"})

    by_job = server.list_job_executions_for_job(job_id)
    assert isinstance(by_job["executions"], list)

    by_thing = server.list_job_executions_for_thing(THING_NAME)
    assert isinstance(by_thing["executions"], list)

    server.delete_job(job_id, confirm=True, force=True)
