# Testing Strategy - Comprehensive Quality Assurance Plan
## Unit, Integration, E2E, Performance, and Security Testing

**Version:** 1.0  
**Date:** August 2026  
**Target Coverage:** >90% code coverage  
**Target Quality:** <0.1% production error rate  

---

## Testing Overview

### Testing Pyramid

```
        ╱╲
       ╱  ╲  E2E Tests (5-10%)
      ╱────╲
     ╱      ╲  Integration Tests (20-30%)
    ╱────────╲
   ╱          ╲  Unit Tests (60-80%)
  ╱────────────╲
```

### Test Types

| Type | Purpose | Tools | Count | Runtime |
|------|---------|-------|-------|---------|
| Unit | Component logic | pytest, Vitest | 200+ | <5 min |
| Integration | Module interaction | pytest, testcontainers | 50+ | 10-15 min |
| E2E | User workflows | Playwright, pytest | 30+ | 15-20 min |
| Performance | Latency & throughput | k6, locust | 10+ | 10 min |
| Security | Vulnerabilities | bandit, safety, OWASP ZAP | ongoing | 5 min |

**Total Runtime:** <45 minutes for full suite

---

## Unit Testing

### Backend Unit Tests (Python)

#### 1. Content Generation Tests

**File:** `tests/unit/test_content_generation.py`

```python
import pytest
from src.services.content import ContentGenerator
from unittest.mock import Mock, patch

class TestContentGenerator:
    """Test content generation service"""
    
    @pytest.fixture
    def generator(self):
        """Create content generator instance"""
        return ContentGenerator()
    
    def test_generate_single_variation(self, generator):
        """Single variation generation"""
        result = generator.generate_single(
            topic="Turkish supply chain",
            platform="linkedin",
            tone="executive"
        )
        
        assert result is not None
        assert result["platform"] == "linkedin"
        assert result["tone"] == "executive"
        assert len(result["text"]) > 0
        assert "hashtags" in result
    
    def test_generate_five_variations(self, generator):
        """Generate exactly 5 variations"""
        result = generator.generate_variations(
            topic="Turkish supply chain",
            primary_platform="linkedin",
            language="both"
        )
        
        assert len(result) == 5
        platforms = [v["platform"] for v in result]
        assert "linkedin" in platforms
        assert "twitter" in platforms
    
    @patch('src.services.gemini.call_api')
    def test_gemini_api_integration(self, mock_gemini, generator):
        """Test Gemini API call"""
        mock_gemini.return_value = {"text": "Generated content"}
        
        result = generator.generate_single(
            topic="test",
            platform="linkedin",
            tone="executive"
        )
        
        mock_gemini.assert_called_once()
        assert result["text"] == "Generated content"
    
    def test_prompt_caching(self, generator):
        """Verify prompt caching works"""
        prompt = "System prompt for content generation"
        
        # First call (cache miss)
        result1 = generator._get_cached_prompt(prompt)
        assert result1 is not None
        
        # Second call (cache hit)
        result2 = generator._get_cached_prompt(prompt)
        
        assert result1 == result2
        # Verify cache was used (lower cost)
        assert generator.cache.get_hit_count() > 0
    
    def test_optimal_posting_time(self, generator):
        """Calculate optimal posting time"""
        time = generator.calculate_optimal_time(
            platform="linkedin",
            audience_timezone="Europe/Istanbul"
        )
        
        assert time is not None
        assert 0 <= time.hour < 24
        # LinkedIn: optimal 6-9 AM in user timezone
        assert time.hour in [6, 7, 8, 9]
    
    @pytest.mark.parametrize("language", ["en", "tr", "both"])
    def test_language_variations(self, generator, language):
        """Test dual-language support"""
        result = generator.generate_single(
            topic="test",
            platform="linkedin",
            language=language
        )
        
        if language in ["tr", "both"]:
            assert any(char in result["text"] for char in "çğıöşüÇĞİÖŞÜ")
        if language in ["en", "both"]:
            assert any(c.isascii() for c in result["text"])
    
    @pytest.mark.parametrize("tone", ["executive", "casual", "critical", "inspirational"])
    def test_tone_variations(self, generator, tone):
        """Test all tone variations"""
        result = generator.generate_single(
            topic="test",
            platform="linkedin",
            tone=tone
        )
        
        assert result["tone"] == tone
        # Verify tone-specific characteristics
        if tone == "executive":
            assert any(word in result["text"].lower() for word in ["strategic", "competitive", "transform"])
        elif tone == "casual":
            assert any(word in result["text"].lower() for word in ["hey", "let's", "great"])
```

#### 2. API Endpoint Tests

**File:** `tests/unit/test_api_endpoints.py`

```python
import pytest
from fastapi.testclient import TestClient
from src.main import app

@pytest.fixture
def client():
    """Create FastAPI test client"""
    return TestClient(app)

@pytest.fixture
def auth_headers(client):
    """Generate valid JWT token"""
    # Mock authentication
    return {"Authorization": "Bearer valid_test_token"}

class TestContentEndpoints:
    """Test content API endpoints"""
    
    def test_generate_content_valid_input(self, client, auth_headers):
        """POST /content/generate with valid input"""
        response = client.post(
            "/api/content/generate",
            json={
                "topic": "Turkish supply chain",
                "primary_platform": "linkedin",
                "language": "both",
                "tone": "executive"
            },
            headers=auth_headers
        )
        
        assert response.status_code == 202
        assert response.json()["success"] == True
        assert "id" in response.json()["data"]
        assert len(response.json()["data"]["variations"]) == 5
    
    def test_generate_content_missing_topic(self, client, auth_headers):
        """POST /content/generate without required topic"""
        response = client.post(
            "/api/content/generate",
            json={
                "primary_platform": "linkedin",
                "language": "both"
            },
            headers=auth_headers
        )
        
        assert response.status_code == 400
        assert "topic" in response.json()["error"]["details"]["field"]
    
    def test_list_content(self, client, auth_headers):
        """GET /content with pagination"""
        response = client.get(
            "/api/content?limit=20&offset=0",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert "items" in response.json()["data"]
        assert "pagination" in response.json()["data"]
    
    def test_unauthorized_request(self, client):
        """Request without authentication"""
        response = client.get("/api/content")
        
        assert response.status_code == 401
        assert "Unauthorized" in response.json()["error"]["message"]
    
    def test_rate_limiting(self, client, auth_headers):
        """Verify rate limiting (100 req/min)"""
        # Send 101 requests
        for i in range(101):
            response = client.get(
                "/api/content",
                headers=auth_headers
            )
        
        # 101st request should be rate limited
        assert response.status_code == 429
```

#### 3. Database Tests

**File:** `tests/unit/test_database.py`

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.models import Base, User, Content

@pytest.fixture
def db_session():
    """Create test database session"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    yield Session()

class TestDatabase:
    """Test database operations"""
    
    def test_create_user(self, db_session):
        """Create user record"""
        user = User(
            email="test@example.com",
            name="Test User",
            language_preference="en"
        )
        db_session.add(user)
        db_session.commit()
        
        retrieved = db_session.query(User).filter_by(email="test@example.com").first()
        assert retrieved is not None
        assert retrieved.name == "Test User"
    
    def test_unique_email_constraint(self, db_session):
        """Email uniqueness constraint"""
        user1 = User(email="duplicate@example.com", name="User 1")
        user2 = User(email="duplicate@example.com", name="User 2")
        
        db_session.add(user1)
        db_session.commit()
        
        db_session.add(user2)
        with pytest.raises(IntegrityError):
            db_session.commit()
    
    def test_create_content(self, db_session):
        """Create content record"""
        user = User(email="test@example.com", name="Test")
        db_session.add(user)
        db_session.commit()
        
        content = Content(
            user_id=user.id,
            title="Test Post",
            topic="Supply Chain",
            status="draft"
        )
        db_session.add(content)
        db_session.commit()
        
        retrieved = db_session.query(Content).filter_by(title="Test Post").first()
        assert retrieved is not None
        assert retrieved.topic == "Supply Chain"
```

### Frontend Unit Tests (React/TypeScript)

**File:** `tests/unit/useContentGeneration.test.tsx`

```typescript
import { renderHook, act, waitFor } from '@testing-library/react';
import { useContentGeneration } from 'src/hooks/useContentGeneration';

describe('useContentGeneration', () => {
  it('generates content variations', async () => {
    const { result } = renderHook(() => useContentGeneration());
    
    await act(async () => {
      await result.current.generate({
        topic: 'Turkish supply chain',
        platform: 'linkedin',
        language: 'both',
        tone: 'executive'
      });
    });
    
    await waitFor(() => {
      expect(result.current.variations).toHaveLength(5);
    });
  });
  
  it('handles generation errors', async () => {
    const { result } = renderHook(() => useContentGeneration());
    
    await act(async () => {
      await result.current.generate({
        topic: '',  // Empty topic
        platform: 'linkedin',
        language: 'en',
        tone: 'executive'
      });
    });
    
    await waitFor(() => {
      expect(result.current.error).toBeDefined();
      expect(result.current.error).toContain('topic');
    });
  });
});
```

---

## Integration Testing

### Database + API Integration

**File:** `tests/integration/test_content_workflow.py`

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.main import app
from fastapi.testclient import TestClient

@pytest.fixture
def db_engine():
    """Create test database"""
    engine = create_engine("postgresql://localhost/test_db")
    yield engine

@pytest.fixture
def client(db_engine):
    """Create test client with database"""
    app.dependency_overrides[get_db] = lambda: SessionLocal(bind=db_engine)
    return TestClient(app)

class TestContentWorkflow:
    """Test end-to-end content workflow"""
    
    def test_generate_and_publish_flow(self, client, db_engine):
        """Complete flow: Generate → Save → Publish"""
        
        # 1. Generate content
        response = client.post(
            "/api/content/generate",
            json={
                "topic": "Test",
                "primary_platform": "linkedin",
                "language": "en",
                "tone": "executive"
            },
            headers={"Authorization": "Bearer valid_token"}
        )
        
        assert response.status_code == 202
        content_id = response.json()["data"]["id"]
        
        # 2. Verify content saved
        response = client.get(
            f"/api/content/{content_id}",
            headers={"Authorization": "Bearer valid_token"}
        )
        
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "draft"
        
        # 3. Publish content
        response = client.post(
            f"/api/content/{content_id}/publish",
            json={
                "platforms": ["linkedin"],
                "schedule_time": None
            },
            headers={"Authorization": "Bearer valid_token"}
        )
        
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "published"
```

### External API Integration

**File:** `tests/integration/test_gemini_api.py`

```python
import pytest
from unittest.mock import patch, MagicMock
from src.services.gemini import GeminiClient

@pytest.mark.integration
class TestGeminiIntegration:
    """Test Gemini API integration (real API)"""
    
    @pytest.fixture
    def client(self):
        return GeminiClient(api_key="test_key")
    
    def test_real_api_call(self, client):
        """Call real Gemini API"""
        response = client.generate(
            prompt="Write a tweet about supply chain",
            model="gemini-2.5-flash"
        )
        
        assert response is not None
        assert len(response) > 0
    
    def test_rate_limiting(self, client):
        """Verify rate limiting (2 req/min free tier)"""
        # Make 3 rapid requests
        try:
            for i in range(3):
                client.generate(prompt="test")
        except RateLimitError:
            pytest.skip("Rate limited as expected")
    
    @patch('src.services.gemini.GeminiClient.generate')
    def test_mock_api_call(self, mock_generate):
        """Mock Gemini API call"""
        mock_generate.return_value = "Mocked response"
        
        client = GeminiClient(api_key="test_key")
        result = client.generate(prompt="test")
        
        assert result == "Mocked response"
        mock_generate.assert_called_once()
```

---

## End-to-End (E2E) Testing

### Browser Automation Tests

**File:** `tests/e2e/test_content_creation.py`

```python
import pytest
from playwright.sync_api import sync_playwright

@pytest.fixture(scope="session")
def browser():
    """Create browser instance"""
    with sync_playwright() as p:
        yield p.chromium.launch()

@pytest.fixture
def page(browser):
    """Create page for each test"""
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()

class TestContentCreationE2E:
    """E2E tests for content creation"""
    
    @pytest.mark.e2e
    def test_user_generates_and_publishes_content(self, page):
        """User journey: Login → Generate → Approve → Publish"""
        
        # 1. Navigate to app
        page.goto("https://localhost:3000")
        
        # 2. Click login
        page.click("text=Login with Google")
        
        # 3. Wait for OAuth redirect
        # (Mocked in test environment)
        page.wait_for_url("**/dashboard")
        
        # 4. Click "Generate Content"
        page.click("text=Generate Content")
        
        # 5. Fill form
        page.fill('input[name="topic"]', "Turkish supply chain")
        page.select_option('select[name="platform"]', "linkedin")
        page.click('text=Executive')
        
        # 6. Submit
        page.click("button:text('Generate')")
        
        # 7. Wait for variations
        page.wait_for_selector("text=5 Variations Generated")
        
        # 8. Approve first variation
        page.click("button:text('Approve')") # First variation
        
        # 9. Confirm publish
        page.click("button:text('Confirm & Publish')")
        
        # 10. Verify success
        assert "✓ Posted to LinkedIn" in page.content()
    
    @pytest.mark.e2e
    def test_user_views_analytics(self, page):
        """User views engagement analytics"""
        
        # Navigate to analytics
        page.goto("https://localhost:3000/analytics")
        
        # Wait for dashboard to load
        page.wait_for_selector("text=Engagement Rate")
        
        # Verify metrics displayed
        assert "3.8%" in page.content()  # Engagement rate
        assert "145" in page.content()   # Followers
        assert "1,240" in page.content() # Total engagement
```

---

## Performance Testing

### Load Testing

**File:** `tests/performance/load_test.js` (k6)

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export let options = {
  vus: 100,           // 100 virtual users
  duration: '5m',     // Run for 5 minutes
  thresholds: {
    http_req_duration: ['p(95)<2000', 'p(99)<5000'],  // P95 < 2s, P99 < 5s
    http_req_failed: ['rate<0.1'],                      // Error rate < 0.1%
  },
};

export default function () {
  // Generate content
  let response = http.post(
    'https://api.content-platform.com/api/content/generate',
    JSON.stringify({
      topic: 'Turkish supply chain',
      platform: 'linkedin',
      language: 'both',
      tone: 'executive',
    }),
    {
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer valid_token',
      },
    }
  );
  
  check(response, {
    'status is 202': (r) => r.status === 202,
    'response time < 10s': (r) => r.timings.duration < 10000,
  });
  
  sleep(1);
  
  // List content
  response = http.get(
    'https://api.content-platform.com/api/content?limit=20',
    {
      headers: { 'Authorization': 'Bearer valid_token' },
    }
  );
  
  check(response, {
    'status is 200': (r) => r.status === 200,
    'response time < 1s': (r) => r.timings.duration < 1000,
  });
  
  sleep(1);
}
```

**Run:** `k6 run tests/performance/load_test.js`

### Stress Testing

**File:** `tests/performance/stress_test.js`

```javascript
// Same as load test but with higher VUs
export let options = {
  stages: [
    { duration: '1m', target: 100 },   // Ramp to 100 users
    { duration: '3m', target: 500 },   // Ramp to 500 users
    { duration: '3m', target: 1000 },  // Ramp to 1000 users
    { duration: '2m', target: 0 },     // Ramp down
  ],
  thresholds: {
    http_req_failed: ['rate<0.5'],  // Allow 0.5% errors under stress
  },
};
```

---

## Security Testing

### OWASP Top 10

**File:** `tests/security/test_owasp.py`

```python
import pytest
from src.main import app
from fastapi.testclient import TestClient

class TestOWASPSecurity:
    """Test OWASP Top 10 vulnerabilities"""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    def test_sql_injection(self, client):
        """SQL Injection prevention"""
        response = client.get(
            "/api/content?search=' OR '1'='1",
            headers={"Authorization": "Bearer valid_token"}
        )
        
        # Should safely handle injection
        assert response.status_code == 200
        # Should not expose database errors
        assert "SQL" not in response.text
        assert "database" not in response.text.lower()
    
    def test_xss_prevention(self, client):
        """XSS prevention"""
        response = client.post(
            "/api/content/generate",
            json={
                "topic": "<script>alert('XSS')</script>",
                "platform": "linkedin",
                "language": "en",
                "tone": "executive"
            },
            headers={"Authorization": "Bearer valid_token"}
        )
        
        assert response.status_code in [202, 400]
        # Content should be sanitized
        content = response.json()
        assert "<script>" not in str(content)
    
    def test_csrf_protection(self, client):
        """CSRF token validation"""
        # POST without CSRF token should fail (if implemented)
        response = client.post(
            "/api/content/generate",
            json={"topic": "test"},
            headers={"Authorization": "Bearer valid_token"}
        )
        
        # Should either require CSRF token or be safe (SameSite cookie)
        # Verify secure headers present
        assert "Set-Cookie" not in response.headers or "SameSite" in response.headers["Set-Cookie"]
    
    def test_authentication_enforcement(self, client):
        """Authentication required on protected endpoints"""
        # No token
        response = client.get("/api/content")
        assert response.status_code == 401
        
        # Invalid token
        response = client.get(
            "/api/content",
            headers={"Authorization": "Bearer invalid_token"}
        )
        assert response.status_code == 401
    
    def test_rate_limiting(self, client):
        """Rate limiting prevents brute force"""
        # Make 101 requests rapidly
        for i in range(101):
            response = client.get(
                "/api/content",
                headers={"Authorization": "Bearer valid_token"}
            )
        
        # 101st should be rate limited
        assert response.status_code == 429
```

### Dependency Vulnerability Scan

```bash
# Check Python dependencies
bandit -r src/
safety check

# Check JavaScript dependencies
npm audit
```

---

## Coverage Requirements

### Code Coverage Targets

```
Overall:        >90%
Backend:        >95%
Frontend:       >80%
Critical paths: >98%

Critical paths:
├─ Authentication
├─ Content generation
├─ Publishing
├─ Database operations
└─ API endpoints
```

### Coverage Report

```bash
# Generate coverage report
pytest tests/ --cov=src --cov-report=html --cov-report=term

# View HTML report
open htmlcov/index.html
```

---

## Test Execution Strategy

### Local Development
```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/unit/test_content_generation.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing

# Run fast unit tests only
pytest tests/unit/ -v
```

### CI/CD Pipeline
```bash
# Run on every push
1. Unit tests (5 min)
2. Integration tests (10 min)
3. Security scan (5 min)
4. Deploy to staging
5. E2E tests (20 min)
6. Load tests (if approved)
```

### Performance Baseline
```bash
# Establish baseline
k6 run tests/performance/baseline.js

# Compare after optimization
k6 run tests/performance/baseline.js --summary-export=baseline.json

# Alert if degradation >5%
```

---

## Monitoring & Quality Metrics

### KPIs

| Metric | Target | Alert |
|--------|--------|-------|
| Code coverage | >90% | <85% |
| Test pass rate | 100% | <99% |
| Critical bugs in prod | 0 | Any |
| P99 latency | <5s | >5s for 5 min |
| Error rate | <0.1% | >0.5% for 5 min |

---

**Document Control**
- Version: 1.0
- Status: FINAL
- Last Updated: August 2026
