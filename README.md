# k8s-guestbook (Pulumi + Kubernetes)

## Deploy the application

1. Install prerequisites: `pulumi`, `kubectl`, `minikube`, Python 3.
2. Start Minikube:
   ```bash
   minikube start
   ```
3. Create/Select stack `sk`:
   ```bash
   pulumi stack init sk
   pulumi stack select sk
   ```
4. Ensure stack config file exists as `Pulumi.sk.yaml`.
5. Install Python dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
6. Deploy:
   ```bash
   pulumi up -s sk
   ```

## Grafana access URL and admin credentials

Get outputs:

```bash
pulumi stack output -s sk grafana_url
pulumi stack output -s sk grafana_admin_user
pulumi stack output -s sk grafana_admin_password
pulumi stack output -s sk grafana_port_forward_command
```

Use port-forward (easy local access):

```bash
$(pulumi stack output -s sk grafana_port_forward_command)
```

Then open:

```text
http://127.0.0.1:3000
```

Login with `grafana_admin_user` and `grafana_admin_password` outputs above.

## Generate traffic (including Guestbook form submits)

Use `traffic_generator.py` to generate concurrent load and simulate Guestbook form submissions.

Example (50 parallel requests x 20 iterations):

```bash
python3 traffic_generator.py --url http://127.0.0.1:8080 --iterations 20 --concurrency 50 --mode auto
```

For Minikube NodePort frontend:

```bash
python3 traffic_generator.py --url "http://$(minikube ip):$(kubectl -n default get svc frontend -o jsonpath='{.spec.ports[0].nodePort}')" --iterations 20 --concurrency 50 --mode auto
```

`--mode auto` discovers the page form and submits messages when possible; otherwise it falls back to GET requests.

## Verify Guestbook metrics are scraped by Prometheus

1. Port-forward Prometheus:
   ```bash
   kubectl -n monitoring port-forward svc/prometheus 9090:9090
   ```
2. Check Prometheus targets (all expected jobs should be `UP`):
   ```bash
   curl -s http://127.0.0.1:9090/api/v1/targets | grep -E '"job"|"health"'
   ```
3. Verify Apache/Guestbook metrics exist:
   ```bash
   curl -s 'http://127.0.0.1:9090/api/v1/query?query=apache_up%7Bjob%3D%22apache-exporter%22%7D'
   ```
4. Verify request counter is increasing:
   ```bash
   curl -s 'http://127.0.0.1:9090/api/v1/query?query=sum%28increase%28%7B__name__%3D~%22apache_accesses_total%7Capache_accesses%7Capache_requests_total%22%2Cjob%3D%22apache-exporter%22%7D%5B5m%5D%29%29'
   ```
