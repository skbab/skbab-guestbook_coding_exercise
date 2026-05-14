from typing import Any, Dict, List, Optional

import pulumi
import yaml
from pulumi_kubernetes.apps.v1 import Deployment
from pulumi_kubernetes.core.v1 import ConfigMap, Namespace, Service, ServiceAccount
from pulumi_kubernetes.rbac.v1 import ClusterRole, ClusterRoleBinding


def create_prometheus_stack(
    monitoring_namespace: Namespace,
    namespace_name: str,
    prometheus_name: str,
    prometheus_port: int,
    prometheus_image: str,
    scrape_interval: str,
    evaluation_interval: str,
    scrape_jobs: List[Dict[str, Any]],
    depends_on: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    base_depends_on = [monitoring_namespace]
    if depends_on:
        base_depends_on.extend(depends_on)
    namespaced_opts = pulumi.ResourceOptions(depends_on=base_depends_on)

    service_account_name = f"{prometheus_name}-sa"
    config_name = f"{prometheus_name}-config"
    role_name = f"{prometheus_name}-read-only"
    role_binding_name = f"{prometheus_name}-read-only-binding"

    ServiceAccount(
        service_account_name,
        metadata={"name": service_account_name, "namespace": namespace_name},
        opts=namespaced_opts,
    )
    ClusterRole(
        role_name,
        metadata={"name": role_name},
        rules=[
            {
                "api_groups": [""],
                "resources": ["nodes", "services", "endpoints", "pods", "namespaces"],
                "verbs": ["get", "list", "watch"],
            },
            {"non_resource_urls": ["/metrics"], "verbs": ["get"]},
        ],
    )
    prometheus_role_binding = ClusterRoleBinding(
        role_binding_name,
        metadata={"name": role_binding_name},
        role_ref={
            "api_group": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": role_name,
        },
        subjects=[{
            "kind": "ServiceAccount",
            "name": service_account_name,
            "namespace": namespace_name,
        }],
        opts=namespaced_opts,
    )

    prometheus_yaml = yaml.safe_dump(
        {
            "global": {
                "scrape_interval": scrape_interval,
                "evaluation_interval": evaluation_interval,
            },
            "scrape_configs": scrape_jobs,
        },
        sort_keys=False,
    )

    prometheus_config = ConfigMap(
        config_name,
        metadata={"name": config_name, "namespace": namespace_name},
        data={"prometheus.yml": prometheus_yaml},
        opts=namespaced_opts,
    )

    prometheus_labels = {"app": prometheus_name}
    prometheus = Deployment(
        prometheus_name,
        metadata={"name": prometheus_name, "namespace": namespace_name, "labels": prometheus_labels},
        spec={
            "replicas": 1,
            "selector": {"match_labels": prometheus_labels},
            "template": {
                "metadata": {"labels": prometheus_labels},
                "spec": {
                    "service_account_name": service_account_name,
                    "containers": [{
                        "name": "prometheus",
                        "image": prometheus_image,
                        "args": [
                            "--config.file=/etc/prometheus/prometheus.yml",
                            "--storage.tsdb.path=/prometheus",
                            "--web.enable-lifecycle",
                        ],
                        "ports": [{"name": "web", "container_port": prometheus_port}],
                        "volume_mounts": [
                            {"name": "prometheus-config", "mount_path": "/etc/prometheus"},
                            {"name": "prometheus-storage", "mount_path": "/prometheus"},
                        ],
                    }],
                    "volumes": [
                        {"name": "prometheus-config", "config_map": {"name": config_name}},
                        {"name": "prometheus-storage", "empty_dir": {}},
                    ],
                },
            },
        },
        opts=pulumi.ResourceOptions(depends_on=[prometheus_config, prometheus_role_binding]),
    )

    prometheus_service = Service(
        prometheus_name,
        metadata={"name": prometheus_name, "namespace": namespace_name, "labels": prometheus_labels},
        spec={
            "ports": [{"name": "web", "port": prometheus_port, "target_port": prometheus_port}],
            "selector": prometheus_labels,
        },
        opts=namespaced_opts,
    )

    return {
        "prometheus": prometheus,
        "prometheus_service": prometheus_service,
    }
