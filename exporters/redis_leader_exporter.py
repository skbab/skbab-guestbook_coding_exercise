from typing import Any, Dict

import pulumi
from pulumi_kubernetes.apps.v1 import Deployment
from pulumi_kubernetes.core.v1 import Namespace, Service


def create_redis_leader_exporter(
    monitoring_namespace: Namespace,
    monitoring_namespace_name: str,
    backend_namespace: str,
    redis_exporter_image: str,
    redis_service_name: str,
    redis_service_port: int,
    exporter_name: str,
    metrics_port: int,
) -> Dict[str, Any]:
    namespaced_opts = pulumi.ResourceOptions(depends_on=[monitoring_namespace])
    redis_leader_exporter_labels = {"app": exporter_name}

    redis_leader_exporter = Deployment(
        exporter_name,
        metadata={
            "name": exporter_name,
            "namespace": monitoring_namespace_name,
            "labels": redis_leader_exporter_labels,
        },
        spec={
            "replicas": 1,
            "selector": {"match_labels": redis_leader_exporter_labels},
            "template": {
                "metadata": {"labels": redis_leader_exporter_labels},
                "spec": {
                    "containers": [{
                        "name": "redis-exporter",
                        "image": redis_exporter_image,
                        "env": [{
                            "name": "REDIS_ADDR",
                            "value": f"redis://{redis_service_name}.{backend_namespace}.svc.cluster.local:{redis_service_port}",
                        }],
                        "ports": [{"name": "metrics", "container_port": metrics_port}],
                    }]
                },
            },
        },
        opts=namespaced_opts,
    )

    redis_leader_exporter_service = Service(
        exporter_name,
        metadata={
            "name": exporter_name,
            "namespace": monitoring_namespace_name,
            "labels": redis_leader_exporter_labels,
            "annotations": {
                "prometheus.io/scrape": "true",
                "prometheus.io/port": str(metrics_port),
            },
        },
        spec={
            "ports": [{"name": "metrics", "port": metrics_port, "target_port": metrics_port}],
            "selector": redis_leader_exporter_labels,
        },
        opts=namespaced_opts,
    )

    return {
        "redis_leader_exporter": redis_leader_exporter,
        "redis_leader_exporter_service": redis_leader_exporter_service,
    }
