import json
from typing import Any, Dict

import pulumi
from pulumi_kubernetes.apps.v1 import Deployment
from pulumi_kubernetes.core.v1 import ConfigMap, Namespace, Service


def create_grafana_stack(
    monitoring_namespace: Namespace,
    namespace_name: str,
    grafana_name: str,
    grafana_port: int,
    grafana_service_type: str,
    grafana_node_port: int,
    grafana_admin_user: str,
    grafana_admin_password: str,
    grafana_image: str,
    prometheus_url: str,
    dashboards: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    namespaced_opts = pulumi.ResourceOptions(depends_on=[monitoring_namespace])

    grafana_datasource_config = ConfigMap(
        f"{grafana_name}-datasource-config",
        metadata={"name": f"{grafana_name}-datasource-config", "namespace": namespace_name},
        data={
            "datasources.yaml": f"""apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: {prometheus_url}
    isDefault: true
    editable: false
"""
        },
        opts=namespaced_opts,
    )
    grafana_dashboard_provider_config = ConfigMap(
        f"{grafana_name}-dashboard-provider-config",
        metadata={"name": f"{grafana_name}-dashboard-provider-config", "namespace": namespace_name},
        data={
            "dashboardproviders.yaml": """apiVersion: 1
providers:
  - name: "default"
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /var/lib/grafana/dashboards
"""
        },
        opts=namespaced_opts,
    )
    grafana_dashboard_config = ConfigMap(
        f"{grafana_name}-dashboard-config",
        metadata={"name": f"{grafana_name}-dashboard-config", "namespace": namespace_name},
        data={file_name: json.dumps(dashboard) for file_name, dashboard in dashboards.items()},
        opts=namespaced_opts,
    )

    grafana_labels = {"app": grafana_name}
    grafana = Deployment(
        grafana_name,
        metadata={"name": grafana_name, "namespace": namespace_name, "labels": grafana_labels},
        spec={
            "replicas": 1,
            "selector": {"match_labels": grafana_labels},
            "template": {
                "metadata": {"labels": grafana_labels},
                "spec": {
                    "containers": [{
                        "name": "grafana",
                        "image": grafana_image,
                        "ports": [{"name": "http", "container_port": grafana_port}],
                        "env": [
                            {"name": "GF_SECURITY_ADMIN_USER", "value": grafana_admin_user},
                            {"name": "GF_SECURITY_ADMIN_PASSWORD", "value": grafana_admin_password},
                        ],
                        "volume_mounts": [
                            {"name": "grafana-datasource-config", "mount_path": "/etc/grafana/provisioning/datasources"},
                            {"name": "grafana-dashboard-provider-config", "mount_path": "/etc/grafana/provisioning/dashboards"},
                            {"name": "grafana-dashboard-config", "mount_path": "/var/lib/grafana/dashboards"},
                        ],
                    }],
                    "volumes": [
                        {"name": "grafana-datasource-config", "config_map": {"name": f"{grafana_name}-datasource-config"}},
                        {"name": "grafana-dashboard-provider-config", "config_map": {"name": f"{grafana_name}-dashboard-provider-config"}},
                        {"name": "grafana-dashboard-config", "config_map": {"name": f"{grafana_name}-dashboard-config"}},
                    ],
                },
            },
        },
        opts=pulumi.ResourceOptions(
            depends_on=[
                grafana_datasource_config,
                grafana_dashboard_provider_config,
                grafana_dashboard_config,
            ]
        ),
    )

    grafana_service_port = {"name": "http", "port": grafana_port, "target_port": grafana_port}
    if grafana_service_type == "NodePort":
        grafana_service_port["node_port"] = grafana_node_port

    grafana_service = Service(
        grafana_name,
        metadata={"name": grafana_name, "namespace": namespace_name, "labels": grafana_labels},
        spec={
            "type": grafana_service_type,
            "ports": [grafana_service_port],
            "selector": grafana_labels,
        },
        opts=namespaced_opts,
    )

    grafana_lb_host = grafana_service.status.apply(
        lambda status: (
            status.get("load_balancer", {}).get("ingress", [{}])[0].get("ip")
            or status.get("load_balancer", {}).get("ingress", [{}])[0].get("hostname")
            if status and status.get("load_balancer", {}).get("ingress")
            else ""
        )
    )
    grafana_node_port_output = grafana_service.spec.apply(
        lambda spec: spec.get("ports", [{}])[0].get("node_port", grafana_port) if spec else grafana_port
    )
    if grafana_service_type == "LoadBalancer":
        grafana_url = grafana_lb_host.apply(lambda host: f"http://{host}:{grafana_port}" if host else "")
    elif grafana_service_type == "NodePort":
        grafana_url = grafana_node_port_output.apply(lambda port: f"http://<node-ip>:{port}")
    else:
        grafana_url = f"http://{grafana_name}.{namespace_name}.svc.cluster.local:{grafana_port}"

    return {
        "grafana": grafana,
        "grafana_service": grafana_service,
        "grafana_url": grafana_url,
        "grafana_node_port": grafana_node_port_output,
        "grafana_admin_user": grafana_admin_user,
        "grafana_admin_password": grafana_admin_password,
    }
