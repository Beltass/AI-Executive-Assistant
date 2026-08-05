# Deployment Strategy - Production Infrastructure & Release Pipeline
## Cloud-Native Deployment on Google Cloud Platform

**Version:** 1.0  
**Date:** August 2026  
**Platform:** Google Cloud Platform (Cloud Run, Cloud SQL, Cloud Storage)  

---

## Deployment Environments

### Development (Local)
**Purpose:** Local development and testing  
**Infrastructure:** Docker Compose  
**Database:** PostgreSQL (local)  
**Cache:** Redis (local)  
**Cost:** Free

**Setup:**
```bash
docker-compose up -d
# Starts: API (port 8000), Frontend (port 3000), PostgreSQL, Redis
```

**Features:**
- Hot reload (FastAPI, React)
- Mock external APIs (LinkedIn, Twitter, Slack)
- Seed database with test data
- Full feature parity with production

---

### Staging
**Purpose:** Pre-production testing, UAT  
**Infrastructure:** Google Cloud Run (us-central1)  
**Database:** Cloud SQL (PostgreSQL)  
**Cache:** Cloud Memorystore (Redis)  
**Cost:** ~$100/month

**Configuration:**
- Auto-scaling: 1-10 instances
- Memory: 2GB per instance
- CPU: 1 vCPU per instance
- Timeout: 300 seconds
- Concurrency: 100 per instance

**Environment:**
```
ENVIRONMENT=staging
LOG_LEVEL=DEBUG
GEMINI_API_TIER=free  # or allocated budget
DATABASE_URL=cloudsql://staging-database
SLACK_APP_TOKEN=xapp_staging_...
```

**Validation:**
- Run all E2E tests
- Manual feature testing
- Performance validation
- Security scanning

---

### Production
**Purpose:** Live user-facing service  
**Infrastructure:** Google Cloud Run (multi-region: us-central1, europe-west1)  
**Database:** Cloud SQL (PostgreSQL, HA replica)  
**Cache:** Cloud Memorystore (Redis, HA)  
**CDN:** Cloud CDN
**Cost:** ~$1,000-5,000/month (scale-dependent)

**Configuration:**
- Auto-scaling: 1-100 instances
- Memory: 2GB per instance
- CPU: 1 vCPU per instance
- Timeout: 300 seconds
- Concurrency: 100 per instance
- Max instances: 100 (cost control)

**Environment:**
```
ENVIRONMENT=production
LOG_LEVEL=INFO
GEMINI_API_TIER=paid
DATABASE_URL=cloudsql://production-database
SLACK_APP_TOKEN=xapp_production_...
```

**SLA:** 99.95% uptime

---

## CI/CD Pipeline

### GitHub Actions Workflow

**File:** `.github/workflows/ci.yml`

```yaml
name: CI/CD Pipeline

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
    
    - name: Run unit tests
      run: pytest tests/unit -v --cov=src --cov-report=xml
    
    - name: Run integration tests
      run: pytest tests/integration -v
      env:
        DATABASE_URL: postgresql://postgres:postgres@localhost/test_db
        REDIS_URL: redis://localhost:6379/0
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
    
    - name: Lint Python
      run: |
        black --check src/
        isort --check-only src/
        pylint src/
    
    - name: Type check Python
      run: mypy src/
    
    - name: Security scan
      run: bandit -r src/

  build:
    needs: test
    runs-on: ubuntu-latest
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'

    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Cloud SDK
      uses: google-github-actions/setup-gcloud@v1
      with:
        service_account_key: ${{ secrets.GCP_SA_KEY }}
        project_id: ${{ secrets.GCP_PROJECT_ID }}
    
    - name: Configure Docker for GCP
      run: |
        gcloud auth configure-docker gcr.io
    
    - name: Build and push Docker image
      run: |
        docker build -t gcr.io/${{ secrets.GCP_PROJECT_ID }}/content-api:latest .
        docker push gcr.io/${{ secrets.GCP_PROJECT_ID }}/content-api:latest

  deploy-staging:
    needs: build
    runs-on: ubuntu-latest
    if: github.event_name == 'push' && github.ref == 'refs/heads/develop'

    steps:
    - uses: actions/checkout@v3
    
    - name: Deploy to Cloud Run (Staging)
      run: |
        gcloud run deploy content-api-staging \
          --image gcr.io/${{ secrets.GCP_PROJECT_ID }}/content-api:latest \
          --platform managed \
          --region us-central1 \
          --allow-unauthenticated
    
    - name: Run smoke tests
      run: |
        curl -f https://content-api-staging-xxx.run.app/health || exit 1

  deploy-production:
    needs: build
    runs-on: ubuntu-latest
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    environment: production

    steps:
    - uses: actions/checkout@v3
    
    - name: Deploy to Cloud Run (Production)
      run: |
        gcloud run deploy content-api \
          --image gcr.io/${{ secrets.GCP_PROJECT_ID }}/content-api:latest \
          --platform managed \
          --region us-central1,europe-west1 \
          --allow-unauthenticated
    
    - name: Health check
      run: |
        curl -f https://content-api-xxx.run.app/health || exit 1
    
    - name: Notify Slack
      uses: slackapi/slack-github-action@v1
      with:
        webhook-url: ${{ secrets.SLACK_DEPLOYMENT_WEBHOOK }}
        payload: |
          {
            "text": "Deployment successful",
            "blocks": [
              {
                "type": "section",
                "text": {
                  "type": "mrkdwn",
                  "text": "✓ Deployed to production\nCommit: ${{ github.sha }}"
                }
              }
            ]
          }
```

---

## Deployment Process

### Stage 1: Testing (CI)
```
1. Clone repository
2. Install dependencies
3. Run unit tests (pytest, >90% coverage)
4. Run integration tests
5. Lint check (Black, isort, pylint)
6. Type check (mypy)
7. Security scan (bandit)
8. If all pass → proceed to build
```

**Exit criteria:**
- Test coverage >90%
- All security checks pass
- No linting errors

---

### Stage 2: Build
```
1. Set up Google Cloud SDK authentication
2. Build Docker image
   - Multi-stage build (optimized)
   - Run security scans (Trivy)
3. Push to Container Registry
4. Tag with:
   - latest
   - git commit hash
   - git tag (if release)
```

**Exit criteria:**
- Image successfully built and pushed
- Security scan passed

---

### Stage 3: Deploy Staging
```
1. Deploy to Cloud Run (staging environment)
2. Wait for deployment to complete (2-5 min)
3. Run smoke tests
   - GET /health → 200 OK
   - GET /api/status → 200 OK
4. Run E2E tests
   - Sample content generation
   - API calls to endpoints
5. Notify team
```

**Exit criteria:**
- Deployment successful
- Health checks passing
- E2E tests passing

---

### Stage 4: Deploy Production (Canary)
```
1. Canary deployment (5% traffic)
   - Route 5% of traffic to new version
   - Monitor error rate and latency
   - Duration: 5-10 minutes
2. If error rate <0.1% and latency normal:
   - Increase to 25% traffic (5-10 min)
   - Then 50% (5-10 min)
   - Then 100% (complete)
3. If error rate >0.1%:
   - Automatic rollback
   - Investigate and fix
   - Re-deploy
```

**Exit criteria:**
- Canary deployment successful
- Error rate <0.1%
- Latency within acceptable range
- No critical logs

---

### Stage 5: Production Validation
```
1. Health check API
2. Validate database connection
3. Validate cache connection
4. Run production smoke tests
5. Verify all external integrations
6. Confirm monitoring active
```

---

## Rollback Strategy

### Automatic Rollback (Canary)
If error rate exceeds threshold:
```
1. Detect anomaly (error rate >0.1% or p99 latency >5s)
2. Immediately route 0% to new version
3. Route 100% to previous stable version
4. Alert team (Slack, email)
5. Investigation window: 1 hour
```

### Manual Rollback
```bash
gcloud run deploy content-api \
  --image gcr.io/PROJECT/content-api:PREVIOUS_TAG \
  --region us-central1,europe-west1
```

### Prevention
- Comprehensive testing before deploy
- Staging environment validation
- Blue-green deployment option (reserve resources)
- Database migrations tested and reversible

---

## Database Migration Strategy

### Pre-Deployment
1. **Migration Testing**
   - Run migrations on staging database
   - Verify data integrity
   - Test rollback procedure
   - Performance impact check

2. **Migration Script**
```sql
-- migrations/001_add_content_table.sql
BEGIN;

CREATE TABLE content (
  id UUID PRIMARY KEY,
  ...
);

-- Verify migration
SELECT COUNT(*) FROM content;

COMMIT;
```

3. **Rollback Script**
```sql
BEGIN;
DROP TABLE content;
COMMIT;
```

### Deployment
1. Pause traffic (drain connections)
2. Run migration
3. Verify data integrity
4. Resume traffic

### Post-Deployment
1. Validate data
2. Monitor database performance
3. Keep rollback available for 24 hours

---

## Secrets Management

### Google Secret Manager
```bash
# Store secrets
gcloud secrets create database_password --data-file=-
gcloud secrets create slack_app_token --data-file=-
gcloud secrets create gemini_api_key --data-file=-

# Access in Cloud Run
gcloud run deploy content-api \
  --update-secrets DATABASE_PASSWORD=database_password:latest \
  --update-secrets SLACK_APP_TOKEN=slack_app_token:latest
```

### Secret Rotation
- Database password: 90 days
- API keys: 90 days
- OAuth tokens: Auto-refresh
- Slack tokens: Auto-refresh

### No Secrets in Code
- Never commit `.env` file
- Use `.env.example` template
- Load from environment at runtime
- Audit all secret access

---

## Monitoring & Alerting

### Key Metrics to Monitor
```
Application:
├─ Request latency (p50, p95, p99)
├─ Error rate (4xx, 5xx)
├─ Throughput (requests/sec)
├─ Active users (concurrent)
└─ Feature-specific metrics

Infrastructure:
├─ CPU utilization
├─ Memory usage
├─ Disk space
├─ Network I/O
└─ Database connection pool

Business:
├─ Content generated (daily)
├─ Posts published (daily)
├─ Engagement rate
├─ Speaking opportunities detected
└─ API cost (Gemini)
```

### Alert Rules
```yaml
# Critical (immediate page)
- ErrorRate > 5% for 5 min
- Latency p99 > 5s for 5 min
- Database unavailable for 3 health checks

# High (within 1 hour)
- ErrorRate > 1% for 15 min
- Latency p95 > 2s for 15 min
- Redis unavailable

# Medium (next business day)
- Queue depth > 10k jobs
- Cache hit rate < 50%
- Database connections > 80%
```

### Dashboards
1. **Operations Dashboard**
   - Real-time system health
   - Error rates and latency
   - Deployment status

2. **Business Dashboard**
   - Users active (daily)
   - Content generated (daily)
   - Engagement metrics
   - Revenue tracking

3. **Infrastructure Dashboard**
   - Cloud Run instances
   - Database performance
   - Cache utilization
   - Storage usage

---

## Scaling Strategy

### Horizontal Scaling
```
Load increases:
1. Auto-scaling detects demand
2. Cloud Run spins up new instances
3. Load balancer routes traffic
4. Max instances: 100 (cost control)

Triggers:
├─ CPU > 80%
├─ Memory > 90%
├─ Request latency p95 > 2s
└─ Concurrent requests > 1000
```

### Vertical Scaling (if needed)
```
If horizontal scaling insufficient:
1. Increase memory per instance: 2GB → 4GB
2. Increase CPU per instance: 1 vCPU → 2 vCPU
3. Monitor cost impact
```

### Database Scaling
```
Connection limits reached:
1. Add connection pooling (PgBouncer)
2. Increase max connections (if needed)
3. Add read replicas for analytics queries
4. Monitor query performance (p99 <100ms)
```

---

## Backup & Disaster Recovery

### Database Backups
```
Frequency: Hourly (automatic, Cloud SQL)
Retention: 7 days
Point-in-time recovery: Last 35 days available

Recovery procedure:
1. Create clone of production database
2. Run tests on clone
3. If verified, promote to primary
4. Estimate RTO: <30 minutes
5. Estimate RPO: <1 hour
```

### File Storage Backups
```
Cloud Storage versioning enabled
- Keep all versions
- Cost: ~10% extra storage

Disaster recovery:
1. Enable cross-region replication
2. Primary: US
3. Backup: EU
4. Test recovery quarterly
```

### Application Deployment Backups
```
Container Registry:
- Keep last 10 images
- Tag with git commit hash
- Tag with release version
- Easy rollback to any version
```

---

## Deployment Checklist

### Pre-Deployment
- [ ] All tests passing (>90% coverage)
- [ ] Code review approved
- [ ] Staging environment passing E2E tests
- [ ] Database migrations reviewed
- [ ] Security scan passed
- [ ] Performance baseline measured
- [ ] Monitoring alerts configured
- [ ] Slack/Email notifications ready
- [ ] Rollback procedure documented
- [ ] Stakeholders notified

### Deployment
- [ ] No traffic manipulation
- [ ] Canary deployment active (5% traffic)
- [ ] Health checks passing
- [ ] Error rate <0.1%
- [ ] Latency within acceptable range
- [ ] Gradual rollout (5% → 25% → 50% → 100%)
- [ ] Database migrations successful
- [ ] Cache warmed up

### Post-Deployment
- [ ] Smoke tests passing
- [ ] User feedback monitoring
- [ ] Metrics baseline established
- [ ] Support team notified
- [ ] Documentation updated
- [ ] Release notes published
- [ ] Team debriefing scheduled

---

## Cost Optimization

### Cloud Run
```
Estimate:
├─ Running: $0.00002400 per vCPU-second
├─ Requests: $0.40 per 1M requests
├─ Data egress: $0.12 per GB
└─ Est. monthly: $200-1000 (scale dependent)
```

**Optimization:**
- Right-size instances (2GB, 1 vCPU)
- Set max instances (100)
- Use Cloud CDN for static assets
- Batch background jobs

### Cloud SQL
```
Estimate:
├─ Instance: $100/month (2 vCPU, 13GB)
├─ Backup storage: $10/month
├─ Data transfer: $12/month
└─ Est. monthly: ~$120
```

**Optimization:**
- Auto-scaling off (predictable workload)
- Scheduled backups
- One replica for HA

### Cloud Storage
```
Estimate:
├─ Storage: $0.020 per GB/month
├─ Operations: $0.0004 per 10k writes
├─ CDN: $0.085 per GB (egress)
└─ Est. monthly: $20-50
```

**Optimization:**
- Lifecycle policies (delete after 90 days)
- Compression where possible
- CDN for frequently accessed files

### Gemini API
```
Estimate:
├─ Input: $0.075 per 1M tokens
├─ Output: $0.30 per 1M tokens
├─ Caching: 53% reduction (prompt cache)
└─ Est. monthly: <$10/user (<$500 at scale)
```

**Optimization:**
- Prompt caching (system prompts)
- Batch requests
- Monitor token usage
- Alert if >$15/user/month

### Total Estimated Cost
```
Development: $50/month (local + minimal staging)
Staging: $100/month
Production: $500-2000/month (scale dependent)
API costs: $300-500/month (Gemini)

Total: $1000-3000/month at launch
```

---

## Deployment Success Metrics

### Reliability
- Deployment success rate: 100% (or near-zero rollbacks)
- Mean Time to Recovery (MTTR): <30 min
- Uptime: 99.95%

### Performance
- Deployment time: <15 min
- Canary validation time: <10 min
- Total deployment: <25 min

### Quality
- Post-deployment errors: 0 critical
- Error rate increase: <0.1%
- Performance regression: <5%

---

## Deployment Schedule

### Regular Deployments
- **Development**: Push triggers automatic deploy to staging
- **Production**: 
  - Merging to `main` triggers production deploy
  - Deployments: Preferred during low-traffic hours (2-4 AM EST)
  - Avoid Fridays if possible (harder to support over weekend)

### Emergency Deployments
- **Rollback only**: Any time (high-priority fixes)
- **Hotfix**: Branched from main, fast-track testing

---

**Document Control**
- Version: 1.0
- Status: FINAL
- Last Updated: August 2026
- Next Review: Month 3 (post-launch)
