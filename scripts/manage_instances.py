import json
import os

import click
import dotenv
import polling2

from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session

AURA_API_ENV = "aura_api.env"

CLIENT_ID = dotenv.get_key(AURA_API_ENV, "CLIENT_ID")
CLIENT_SECRET = dotenv.get_key(AURA_API_ENV, "CLIENT_SECRET")
TOKEN_URL = dotenv.get_key(AURA_API_ENV, "TOKEN_URL")
API_BASE_URL = dotenv.get_key(AURA_API_ENV, "API_BASE_URL")

INSTANCE_TYPES = ("enterprise-ds", "enterprise-db", "professional-ds", "professional-db")
project_NAMES = ("gcp", "aws", "azure")
project_REGIONS = {
    "gcp": "europe-west1",
    "aws": "eu-west-1",
    "azure": "northeurope",
}


def init_oauth_session():
    client = BackendApplicationClient(client_id=CLIENT_ID)
    oauth_session = OAuth2Session(client=client)

    oauth_session.fetch_token(TOKEN_URL, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

    return oauth_session


def list_instances(oauth_session):
    res = oauth_session.get(f"{API_BASE_URL}/instances")
    res.raise_for_status()

    print(json.dumps(res.json(), indent=2))


def get_project(oauth_session, project_name):
    res = oauth_session.get(f"{API_BASE_URL}/projects")
    res.raise_for_status()

    res_json = res.json()
    if "data" in res_json:
        for project in res_json["data"]:
            if project["name"].endswith(f"-{project_name}"):
                return project["id"]

    raise ValueError(f"project '{project_name}' not found")


def get_dotenv_filename(instance_name):
    return instance_name + ".env"


def write_dotenv_file(aura_env_file, instance_data):
    dotenv.set_key(aura_env_file, "NEO4J_URI", instance_data["connection_url"])
    dotenv.set_key(aura_env_file, "NEO4J_USERNAME", instance_data["username"])
    dotenv.set_key(aura_env_file, "NEO4J_PASSWORD", instance_data["password"])
    dotenv.set_key(aura_env_file, "AURA_INSTANCEID", instance_data["id"])


def create_instance(oauth_session, instance_type, instance_name, project):
    if instance_type not in INSTANCE_TYPES:
        raise ValueError(f"Instance type {instance_type} not allowed")

    aura_env_file = get_dotenv_filename(instance_name)

    if os.path.exists(aura_env_file):
        raise FileExistsError(f"The env file for an instance named {instance_name} already exists")

    region = project_REGIONS[project]
    project_id = get_project(oauth_session, project)

    body = {
        "version": "5",
        "name": instance_name,
        "type": instance_type,
        "region": region,
        "memory": "8GB",
        "project_id": project_id,
    }
    res = oauth_session.post(f"{API_BASE_URL}/instances", json=body)
    res.raise_for_status()

    instance_data = res.json()["data"]
    write_dotenv_file(aura_env_file, instance_data)

    connection_url = instance_data["connection_url"]
    instance_id = instance_data["id"]

    print(f"Creating instance: {connection_url}")

    def is_instance_running(response):
        return response.json()["data"]["status"] == "running"

    polling2.poll(
        lambda: oauth_session.get(f"{API_BASE_URL}/instances/{instance_id}"),
        check_success=is_instance_running,
        step=10,
        timeout=300,
    )

    print(f"Instance created: {connection_url}")


def destroy_instance(oauth_session, instance_name):
    aura_env_file = get_dotenv_filename(instance_name)

    if not os.path.exists(aura_env_file):
        raise FileNotFoundError(f"The env file for an instance named {instance_name} does not exist")

    connection_url = dotenv.get_key(aura_env_file, "NEO4J_URI")
    instance_id = dotenv.get_key(aura_env_file, "AURA_INSTANCEID")

    print(f"Destroying instance: {connection_url}")

    res = oauth_session.delete(f"{API_BASE_URL}/instances/{instance_id}")
    res.raise_for_status()


@click.command()
@click.option("--create", default=False, is_flag=True, help="Create an Aura instance")
@click.option("--destroy", default=False, is_flag=True, help="Destroy an Aura instance")
@click.option(
    "--instance-type",
    default="enterprise-ds",
    type=click.Choice(INSTANCE_TYPES),
    help="The type of instance to create",
)
@click.option(
    "--project",
    default="gcp",
    type=click.Choice(project_NAMES),
    help="The name of the project to use",
)
@click.argument("instance_name")
def main(create, destroy, instance_type, instance_name, project):
    """Create or destroy an instance with name INSTANCE_NAME."""
    oauth_session = None

    if create or destroy:
        oauth_session = init_oauth_session()

    if create:
        create_instance(oauth_session, instance_type, instance_name, project)

    if destroy:
        destroy_instance(oauth_session, instance_name)

    if oauth_session is not None:
        oauth_session.close()


if __name__ == "__main__":
    main()
