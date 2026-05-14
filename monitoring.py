import json
from pathlib import Path
from typing import Any, Dict, List

from pulumi_kubernetes.core.v1 import Namespace

from exporters.apache_exporter import create_frontend_apache_metrics_service
from exporters.custom_exporters import create_custom_exporters
from exporters.redis_leader_exporter import create_redis_leader_exporter
from exporters.redis_replica_exporter import create_redis_replica_exporter
from grafana import create_grafana_stack
from prometheus import create_prometheus_stack


def _load_dashboard_files(base_dir: Path, dashboard_files: List[str]) -> Dict[str, Dict[str, Any]]:
    dashboards: Dict[str, Dict[str, Any]] = {}
    for dashboard_file in dashboard_files:
        path = (base_dir / dashboard_file).resolve()
        with path.open("r", encoding="utf-8") as f:
            dashboards[path.name] = json.load(f)
    return dashboards


def _render_scrape_jobs(scrape_jobs: List[Dict[str, Any]], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    rendered: List[Dict[str, Any]] = []
    for job in scrape_jobs:
        rendered_job = json.loads(json.dumps(job))
        for static in rendered_job.get("static_configs", []):
            static["targets"] = [target.format(**context) for target in static.get("targets", [])]
        rendered.append(rendered_job)
    return rendered


def _create_exporters_stack(
    monitoring_namespace: Namespace,
    frontend_namespace: str,
    frontend_selector_app: str,
    backend_namespace: str,
    settings: Dict[str, Any],
    redis_exporter_image: str,
    custom_exporters: List[Dict[str, Any]],
) -> Dict[str, Any]:
    apache_resources = create_frontend_apache_metrics_service(
        frontend_namespace=frontend_namespace,
        frontend_selector_app=frontend_selector_app,
        service_name=settings["frontend_apache_metrics_service_name"],
        metrics_port=settings["apache_exporter_metrics_port"],
    )
    redis_leader_resources = create_redis_leader_exporter(
        monitoring_namespace=monitoring_namespace,
        monitoring_namespace_name=settings["monitoring_namespace_name"],
        backend_namespace=backend_namespace,
        redis_exporter_image=redis_exporter_image,
        redis_service_name=settings["redis_leader_service_name"],
        redis_service_port=settings["redis_service_port"],
        exporter_name=settings["redis_leader_exporter_name"],
        metrics_port=settings["redis_exporter_metrics_port"],
    )
    redis_replica_resources = create_redis_replica_exporter(
        monitoring_namespace=monitoring_namespace,
        monitoring_namespace_name=settings["monitoring_namespace_name"],
        backend_namespace=backend_namespace,
        redis_exporter_image=redis_exporter_image,
        redis_service_name=settings["redis_replica_service_name"],
        redis_service_port=settings["redis_service_port"],
        exporter_name=settings["redis_replica_exporter_name"],
        metrics_port=settings["redis_exporter_metrics_port"],
    )
    custom_resources = create_custom_exporters(
        monitoring_namespace=monitoring_namespace,
        default_namespace=settings["monitoring_namespace_name"],
        exporters=custom_exporters,
    )

    return {
        **apache_resources,
        **redis_leader_resources,
        **redis_replica_resources,
        **custom_resources,
    }


def create_monitoring_stack(
    frontend_namespace: str,
    frontend_selector_app: str,
    backend_namespace: str,
    app_cfg: Dict[str, Any],
    images_cfg: Dict[str, Any],
    monitoring_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    namespace_name = monitoring_cfg["namespace"]
    apache_cfg = monitoring_cfg["apacheExporter"]
    redis_exporter_cfg = monitoring_cfg["redisExporters"]
    prometheus_cfg = monitoring_cfg["prometheus"]
    grafana_cfg = monitoring_cfg["grafana"]

    monitoring_namespace = Namespace(namespace_name, metadata={"name": namespace_name})

    exporter_settings = {
        "monitoring_namespace_name": namespace_name,
        "frontend_apache_metrics_service_name": apache_cfg["metricsServiceName"],
        "apache_exporter_metrics_port": apache_cfg["metricsPort"],
        "redis_leader_service_name": app_cfg["redisLeader"]["serviceName"],
        "redis_replica_service_name": app_cfg["redisReplica"]["serviceName"],
        "redis_service_port": app_cfg["redisLeader"]["servicePort"],
        "redis_exporter_metrics_port": redis_exporter_cfg["metricsPort"],
        "redis_leader_exporter_name": redis_exporter_cfg["leaderName"],
        "redis_replica_exporter_name": redis_exporter_cfg["replicaName"],
    }

    exporters_resources = _create_exporters_stack(
        monitoring_namespace=monitoring_namespace,
        frontend_namespace=frontend_namespace,
        frontend_selector_app=frontend_selector_app,
        backend_namespace=backend_namespace,
        settings=exporter_settings,
        redis_exporter_image=images_cfg["redisExporter"],
        custom_exporters=monitoring_cfg.get("extraExporters", []),
    )

    exporter_dependencies = [
        exporters_resources["frontend_apache_metrics_service"],
        exporters_resources["redis_leader_exporter_service"],
        exporters_resources["redis_replica_exporter_service"],
    ]
    for exporter in monitoring_cfg.get("extraExporters", []):
        key = f"{exporter['name']}_service"
        if key in exporters_resources:
            exporter_dependencies.append(exporters_resources[key])

    scrape_context = {
        "frontend_namespace": frontend_namespace,
        "monitoring_namespace": namespace_name,
        "apache_metrics_service": apache_cfg["metricsServiceName"],
        "apache_metrics_port": apache_cfg["metricsPort"],
        "redis_leader_exporter_name": redis_exporter_cfg["leaderName"],
        "redis_replica_exporter_name": redis_exporter_cfg["replicaName"],
        "redis_exporter_metrics_port": redis_exporter_cfg["metricsPort"],
        "prometheus_name": prometheus_cfg["name"],
        "prometheus_port": prometheus_cfg["port"],
    }
    scrape_jobs = _render_scrape_jobs(prometheus_cfg["scrapeJobs"], scrape_context)

    prometheus_resources = create_prometheus_stack(
        monitoring_namespace=monitoring_namespace,
        namespace_name=namespace_name,
        prometheus_name=prometheus_cfg["name"],
        prometheus_port=prometheus_cfg["port"],
        prometheus_image=images_cfg["prometheus"],
        scrape_interval=prometheus_cfg["scrapeInterval"],
        evaluation_interval=prometheus_cfg["evaluationInterval"],
        scrape_jobs=scrape_jobs,
        depends_on=exporter_dependencies,
    )

    dashboards = _load_dashboard_files(Path(__file__).parent, grafana_cfg["dashboardFiles"])
    prometheus_url = (
        f"http://{prometheus_cfg['name']}.{namespace_name}.svc.cluster.local:{prometheus_cfg['port']}"
    )
    grafana_resources = create_grafana_stack(
        monitoring_namespace=monitoring_namespace,
        namespace_name=namespace_name,
        grafana_name=grafana_cfg["name"],
        grafana_port=grafana_cfg["port"],
        grafana_service_type=grafana_cfg["serviceType"],
        grafana_node_port=grafana_cfg["nodePort"],
        grafana_admin_user=grafana_cfg["adminUser"],
        grafana_admin_password=grafana_cfg["adminPassword"],
        grafana_image=images_cfg["grafana"],
        prometheus_url=prometheus_url,
        dashboards=dashboards,
    )

    return {
        "namespace": monitoring_namespace,
        **exporters_resources,
        **prometheus_resources,
        **grafana_resources,
    }
