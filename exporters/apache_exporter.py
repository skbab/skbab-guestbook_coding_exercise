from typing import Any, Dict

from pulumi_kubernetes.core.v1 import Service


def create_frontend_apache_metrics_service(
    frontend_namespace: str,
    frontend_selector_app: str,
    service_name: str,
    metrics_port: int,
) -> Dict[str, Any]:
    frontend_apache_metrics_service = Service(
        service_name,
        metadata={
            "name": service_name,
            "namespace": frontend_namespace,
            "labels": {"app": service_name},
        },
        spec={
            "ports": [{"name": "metrics", "port": metrics_port, "target_port": metrics_port}],
            "selector": {"app": frontend_selector_app},
        },
    )

    return {
        "frontend_apache_metrics_service": frontend_apache_metrics_service,
    }
