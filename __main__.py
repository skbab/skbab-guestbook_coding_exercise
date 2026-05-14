# __main__.py

import pulumi
from pulumi_kubernetes.apps.v1 import Deployment
from pulumi_kubernetes.core.v1 import Service
from pulumi_random import RandomPassword

from monitoring import create_monitoring_stack

# Create only services of type `ClusterIP`
# for clusters that don't support `LoadBalancer` services
config = pulumi.Config()
useLoadBalancer = config.get_bool("useLoadBalancer")
images_cfg = config.require_object("images")
monitoring_cfg = config.require_object("monitoring")

grafana_cfg = monitoring_cfg["grafana"]
grafana_password = RandomPassword(
    "grafana-admin-password",
    length=grafana_cfg.get("adminPasswordLength", 24),
    special=True,
).result
grafana_cfg["adminPassword"] = pulumi.Output.secret(grafana_password)

redis_leader_labels = {
    "app": "redis-leader",
}

redis_leader_deployment = Deployment(
    "redis-leader",
    spec={
        "selector": {
            "match_labels": redis_leader_labels,
        },
        "replicas": 1,
        "template": {
            "metadata": {
                "labels": redis_leader_labels,
            },
            "spec": {
                "containers": [{
                    "name": "redis-leader",
                    "image": "redis",
                    "resources": {
                        "requests": {
                            "cpu": "100m",
                            "memory": "100Mi",
                        },
                    },
                    "ports": [{
                        "container_port": 6379,
                    }],
                }],
            },
        },
    })

redis_leader_service = Service(
    "redis-leader",
    metadata={
        "name": "redis-leader",
        "labels": redis_leader_labels,
    },
    spec={
        "ports": [{
            "port": 6379,
            "target_port": 6379,
        }],
        "selector": redis_leader_labels,
    })

redis_replica_labels = {
    "app": "redis-replica",
}

redis_replica_deployment = Deployment(
    "redis-replica",
    spec={
        "selector": {
            "match_labels": redis_replica_labels,
        },
        "replicas": 1,
        "template": {
            "metadata": {
                "labels": redis_replica_labels,
            },
            "spec": {
                "containers": [{
                    "name": "redis-replica",
                    "image": "pulumi/guestbook-redis-replica",
                    "resources": {
                        "requests": {
                            "cpu": "100m",
                            "memory": "100Mi",
                        },
                    },
                    "env": [{
                        "name": "GET_HOSTS_FROM",
                        "value": "dns",
                        # If your cluster config does not include a dns service, then to instead access an environment
                        # variable to find the leader's host, comment out the 'value: dns' line above, and
                        # uncomment the line below:
                        # value: "env"
                    }],
                    "ports": [{
                        "container_port": 6379,
                    }],
                }],
            },
        },
    })

redis_replica_service = Service(
    "redis-replica",
    metadata={
        "name": "redis-replica",
        "labels": redis_replica_labels,
    },
    spec={
        "ports": [{
            "port": 6379,
            "target_port": 6379,
        }],
        "selector": redis_replica_labels,
    })

# Frontend
frontend_labels = {
    "app": "frontend",
}

frontend_deployment = Deployment(
    "frontend",
    spec={
        "selector": {
            "match_labels": frontend_labels,
        },
        "replicas": 3,
        "template": {
            "metadata": {
                "labels": frontend_labels,
            },
            "spec": {
                "containers": [
                    {
                        "name": "php-redis",
                        "image": "pulumi/guestbook-php-redis",
                        "resources": {
                            "requests": {
                                "cpu": "100m",
                                "memory": "100Mi",
                            },
                        },
                        "env": [{
                            "name": "GET_HOSTS_FROM",
                            "value": "dns",
                            # If your cluster config does not include a dns service, then to instead access an environment
                            # variable to find the leader's host, comment out the 'value: dns' line above, and
                            # uncomment the line below:
                            # "value": "env"
                        }],
                        "ports": [{
                            "container_port": 80,
                        }],
                    },
                    {
                        "name": "apache-exporter",
                        "image": images_cfg["apacheExporter"],
                        "args": [f"--scrape_uri={monitoring_cfg['apacheExporter']['scrapeUri']}"],
                        "ports": [{
                            "name": "metrics",
                            "container_port": monitoring_cfg["apacheExporter"]["metricsPort"],
                        }],
                    },
                ],
            },
        },
    })

frontend_service = Service(
    "frontend",
    metadata={
        "name": "frontend",
        "labels": frontend_labels,
    },
    spec={
        "type": "LoadBalancer" if useLoadBalancer else "ClusterIP",
        "ports": [{
            "port": 80,
        }],
        "selector": frontend_labels,
    })

app_cfg = {
    "namespace": "default",
    "backendNamespace": "default",
    "frontend": {
        "appLabel": "frontend",
        "serviceName": "frontend",
        "servicePort": 80,
        "containerPort": 80,
        "replicas": 3,
    },
    "redisLeader": {
        "serviceName": "redis-leader",
        "servicePort": 6379,
        "containerPort": 6379,
        "replicas": 1,
    },
    "redisReplica": {
        "serviceName": "redis-replica",
        "servicePort": 6379,
        "containerPort": 6379,
        "replicas": 1,
    },
}

monitoring_resources = create_monitoring_stack(
    frontend_namespace=app_cfg["namespace"],
    frontend_selector_app=app_cfg["frontend"]["appLabel"],
    backend_namespace=app_cfg["backendNamespace"],
    app_cfg=app_cfg,
    images_cfg=images_cfg,
    monitoring_cfg=monitoring_cfg,
)

frontend_ip = ""
if useLoadBalancer:
    ingress = frontend_service.status.apply(lambda status: status["load_balancer"]["ingress"][0])
    frontend_ip = ingress.apply(lambda ingress: ingress.get("ip", ingress.get("hostname", "")))
else:
    frontend_ip = frontend_service.spec.apply(lambda spec: spec.get("cluster_ip", ""))
pulumi.export("frontend_ip", frontend_ip)

prometheus_service_host = monitoring_resources["prometheus_service"].metadata.apply(
    lambda metadata: f"{metadata.get('name')}.{metadata.get('namespace')}.svc.cluster.local"
)
prometheus_service_port = monitoring_resources["prometheus_service"].spec.apply(
    lambda spec: spec.get("ports", [{}])[0].get("port", monitoring_cfg["prometheus"]["port"])
)
prometheus_service_url = pulumi.Output.all(prometheus_service_host, prometheus_service_port).apply(
    lambda values: f"http://{values[0]}:{values[1]}"
)

grafana_service_host = monitoring_resources["grafana_service"].metadata.apply(
    lambda metadata: f"{metadata.get('name')}.{metadata.get('namespace')}.svc.cluster.local"
)
grafana_service_port = monitoring_resources["grafana_service"].spec.apply(
    lambda spec: spec.get("ports", [{}])[0].get("port", monitoring_cfg["grafana"]["port"])
)
grafana_service_dns = pulumi.Output.all(grafana_service_host, grafana_service_port).apply(
    lambda values: f"{values[0]}:{values[1]}"
)
grafana_service_type_output = monitoring_resources["grafana_service"].spec.apply(
    lambda spec: spec.get("type", "ClusterIP")
)
grafana_port_forward_command = pulumi.Output.all(
    monitoring_resources["grafana_service"].metadata,
    monitoring_resources["grafana_service"].spec,
).apply(
    lambda values: (
        f"kubectl -n {values[0].get('namespace')} "
        f"port-forward svc/{values[0].get('name')} "
        f"{values[1].get('ports', [{}])[0].get('port', monitoring_cfg['grafana']['port'])}:"
        f"{values[1].get('ports', [{}])[0].get('port', monitoring_cfg['grafana']['port'])}"
    )
)

pulumi.export("prometheus_service", prometheus_service_url)
pulumi.export("grafana_service", grafana_service_dns)
pulumi.export("grafana_service_type", grafana_service_type_output)
pulumi.export("grafana_node_port", monitoring_resources["grafana_node_port"])
pulumi.export("grafana_url", monitoring_resources["grafana_url"])
pulumi.export("grafana_admin_user", monitoring_resources["grafana_admin_user"])
pulumi.export("grafana_admin_password", pulumi.Output.unsecret(monitoring_resources["grafana_admin_password"]))
pulumi.export("grafana_port_forward_command", grafana_port_forward_command)
