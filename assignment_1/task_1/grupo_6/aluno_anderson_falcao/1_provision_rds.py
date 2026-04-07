"""
Provisionamento da instância MySQL no Amazon RDS
"""

import boto3
import json
import os
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()
# ─────────────────────────────────────────────
# CONFIGURAÇÕES — edite antes de executar
# ─────────────────────────────────────────────
CONFIG = {
    "region":              "us-east-1",
    "db_instance_id":      "classicmodels-db",
    "db_name":             "classicmodels",
    "master_username":     os.getenv("USERNAME"),
    "master_password":     os.getenv("PASSWORD"),
    "instance_class":      "db.t3.micro",       # elegível ao Free Tier
    "engine_version":      "8.0",
    "allocated_storage":   20,                  # GB
    "publicly_accessible": True,                # necessário para acesso local
    "credentials_file":    "rds_credentials.json",
}
# ─────────────────────────────────────────────


def get_or_create_security_group(ec2, group_name: str) -> str:
    """Retorna o ID de um security group que libera MySQL (3306) publicamente."""
    try:
        resp = ec2.describe_security_groups(GroupNames=[group_name])
        sg_id = resp["SecurityGroups"][0]["GroupId"]
        print(f"  Security group já existe: {sg_id}")
        return sg_id
    except ClientError:
        pass  # não existe, vamos criar

    vpc_id = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])[
        "Vpcs"
    ][0]["VpcId"]

    sg = ec2.create_security_group(
        GroupName=group_name,
        Description="Acesso MySQL para o laboratorio classicmodels",
        VpcId=vpc_id,
    )
    sg_id = sg["GroupId"]

    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 3306,
                "ToPort": 3306,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "MySQL publico"}],
            }
        ],
    )
    print(f"  Security group criado e configurado: {sg_id}")
    return sg_id


def provision_rds(cfg: dict) -> dict:
    session = boto3.Session(region_name=cfg["region"])
    rds = session.client("rds")
    ec2 = session.client("ec2")

    sg_name = f"{cfg['db_instance_id']}-sg"
    print(f"\n[1/3] Configurando security group '{sg_name}'...")
    sg_id = get_or_create_security_group(ec2, sg_name)

    # Verifica se a instância já existe
    try:
        resp = rds.describe_db_instances(DBInstanceIdentifier=cfg["db_instance_id"])
        status = resp["DBInstances"][0]["DBInstanceStatus"]
        endpoint = resp["DBInstances"][0].get("Endpoint", {}).get("Address", "pending")
        print(f"\n[2/3] Instância já existe (status: {status}).")
        print(f"      Endpoint: {endpoint}")
        return build_credentials(cfg, endpoint)
    except ClientError as e:
        if "DBInstanceNotFound" not in str(e):
            raise

    print(f"\n[2/3] Criando instância RDS '{cfg['db_instance_id']}' ...")
    rds.create_db_instance(
        DBInstanceIdentifier=cfg["db_instance_id"],
        DBName=cfg["db_name"],
        MasterUsername=cfg["master_username"],
        MasterUserPassword=cfg["master_password"],
        DBInstanceClass=cfg["instance_class"],
        Engine="mysql",
        EngineVersion=cfg["engine_version"],
        AllocatedStorage=cfg["allocated_storage"],
        PubliclyAccessible=cfg["publicly_accessible"],
        VpcSecurityGroupIds=[sg_id],
        BackupRetentionPeriod=0,   # sem backups automáticos (lab)
        MultiAZ=False,
        Tags=[{"Key": "Project", "Value": "classicmodels-lab"}],
    )

    print("\n[3/3] Aguardando instância ficar disponível (pode levar ~5 min)...")
    waiter = rds.get_waiter("db_instance_available")
    waiter.wait(
        DBInstanceIdentifier=cfg["db_instance_id"],
        WaiterConfig={"Delay": 20, "MaxAttempts": 30},
    )

    resp = rds.describe_db_instances(DBInstanceIdentifier=cfg["db_instance_id"])
    endpoint = resp["DBInstances"][0]["Endpoint"]["Address"]
    port = resp["DBInstances"][0]["Endpoint"]["Port"]
    print(f"\n   Instância disponível!")
    print(f"     Endpoint : {endpoint}")
    print(f"     Porta    : {port}")

    return build_credentials(cfg, endpoint, port)


def build_credentials(cfg: dict, endpoint: str, port: int = 3306) -> dict:
    return {
        "host":     endpoint,
        "port":     port,
        "database": cfg["db_name"],
        "username": cfg["master_username"],
        "password": cfg["master_password"],
        "region":   cfg["region"],
        "instance": cfg["db_instance_id"],
    }


def save_credentials(creds: dict, filepath: str) -> None:
    with open(filepath, "w") as f:
        json.dump(creds, f, indent=2)
    print(f"\n   Credenciais salvas em '{filepath}'")


def main():
    print("=" * 55)
    print("  Provisionamento RDS MySQL — classicmodels lab")
    print("=" * 55)

    creds = provision_rds(CONFIG)
    save_credentials(creds, CONFIG["credentials_file"])

    print("\n" + "=" * 55)
    print("  RESUMO DE ACESSO")
    print("=" * 55)
    for k, v in creds.items():
        label = k.ljust(12)
        print(f"  {label}: {v}")
    print("=" * 55)


if __name__ == "__main__":
    main()
