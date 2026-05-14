from typing import Any, Dict, List

import pulumi
from pulumi_kubernetes.apps.v1 import Deployment
from pulumi_kubernetes.core.v1 import Namespace, Service


def create_custom_exporters(
    monitoring_namespace: Namespace,
    default_namespace: str,
    exporters: List[Dict[str, Any]],
) -> Dict[str, Any]:
    resources: Dict[str, Any] = {}
    for exporter in exporters:
        name = exporter["name"]
        namespace = exporter.get("namespace", default_namespace)
        labels = exporter.get("labels", {"app": name})
        deployment_name = exporter.get("deploymentName", name)
        service_name = exporter.get("serviceName", name)
        container_name = exporter.get("containerName", name)
        replicas = exporter.get("replicas", 1)
        container_port = exporter["containerPort"]
        service_port = exporter.get("servicePort", container_port)
        env = exporter.get("env", {})

        if isinstance(env, dict):
            env_list = [{"name": key, "value": str(value)} for key, value in env.items()]
        else:
            env_list = env

        namespaced_opts = pulumi.ResourceOptions(depends_on=[monitoring_namespace])

        deployment = Deployment(
            deployment_name,
            metadata={"name": deployment_name, "namespace": namespace, "labels": labels},
            spec={
                "replicas": replicas,
                "selector": {"match_labels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "containers": [{
                            "name": container_name,
                            "image": exporter["image"],
                            "args": exporter.get("args", []),
                            "env": env_list,
                            "ports": [{"name": "metrics", "container_port": container_port}],
                        }]
                    },
                },
            },
            opts=namespaced_opts,
        )

        service = Service(
            service_name,
            metadata={
                "name": service_name,
                "namespace": namespace,
                "labels": labels,
                "annotations": {
                    "prometheus.io/scrape": "true",
                    "prometheus.io/port": str(service_port),
                },
            },
            spec={
                "ports": [{"name": "metrics", "port": service_port, "target_port": container_port}],
                "selector": labels,
            },
            opts=namespaced_opts,
        )

        resources[f"{name}_deployment"] = deployment
        resources[f"{name}_service"] = service

    return resources
