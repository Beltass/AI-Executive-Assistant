# Dashboard Report Organization Structure

## Overview

The "İçerik & Raporlar" (Content & Reports) dashboard tab has been enhanced with intelligent organization of reports using two complementary taxonomies:

1. **Topic-Based Organization** — Groups reports by business domain
2. **Expertise-Based Organization** — Groups reports by advisor expertise area

This dual organization allows users to discover insights through either lens: by domain area or by the specialist who created the analysis.

## Topic-Based Sections

### 1. 📊 İş Analitikleri (Business Analytics)
Reports focused on business performance, data analysis, and strategic insights.

**Associated Advisors:**
- Sektör & Rakip İstihbarat (Sector Intelligence)
- İş Analizi (Business Analysis)
- Veri Analisti (Data Analyst)
- Operasyon Müdürü (Operations Director)

**Report Types:**
- Performance metrics
- Trend analysis
- Market comparisons
- Industry benchmarks
- Operational efficiency reports

---

### 2. 👥 İnsan Kaynakları (HR)
Reports on team performance, career development, and human resources.

**Associated Advisors:**
- Kariyer & İK Danışmanı (Career & HR Advisor)
- İş Avcısı & Başvuru Hazırlayıcı (Job Scout)
- Liderlik Koçu (Leadership Coach)
- Kişisel Gelişim Danışmanı (Personal Development Advisor)
- Çocuk Gelişimi Danışmanı (Child Development Advisor)

**Report Types:**
- Team performance reviews
- Career path recommendations
- Development tracking
- Coaching insights
- HR analytics

---

### 3. 💼 Pazarlama & Satış (Marketing & Sales)
Reports on market opportunities, customer insights, and sales intelligence.

**Associated Advisors:**
- Müşteri Deneyimi Araştırmaları (Customer Experience Research)
- Pazarlama Stratejisi (Marketing Strategy)
- Satış Fırsatları (Sales Opportunities)

**Report Types:**
- Market intelligence
- Customer insights
- Opportunity analysis
- Competitive positioning
- Campaign recommendations

---

### 4. 🚀 İnovasyon (Innovation & Tech)
Reports on innovation, technology trends, and AI advancements.

**Associated Advisors:**
- Yapay Zeka İnovasyon (AI Innovation Lab)
- AI Haberler (AI News)
- Teknoloji Trendleri (Tech Trends)
- Teknoloji Ustası (Technology Master)

**Report Types:**
- Innovation ideas
- Technology trends
- AI applications
- Research findings
- Technical recommendations

---

### 5. 📧 İletişim (Communications)
Reports on communications analysis, email management, and collaboration.

**Associated Advisors:**
- İletişim Danışmanı (Communications Advisor)
- E-Posta Analisti (Email Analyst)
- Takvim & Toplantı Yöneticisi (Calendar & Meeting Manager)

**Report Types:**
- Email analysis
- Meeting notes and summary
- Communication patterns
- Collaboration insights
- Interaction analytics

---

### 6. 📚 Gelişim (Learning & Development)
Reports on personal learning, skill development, and knowledge.

**Associated Advisors:**
- Kişisel Gelişim (Personal Development)
- Dil Koçu (Language Coach)
- Kariyer Gelişim (Career Development)
- Öğrenme Kaynakları (Learning Resources)

**Report Types:**
- Career paths
- Learning resources
- Skill recommendations
- Development plans
- Progress tracking

---

### 7. 🏠 Kişisel & Aile (Personal & Family)
Reports on personal wellness, family matters, and lifestyle.

**Associated Advisors:**
- Hava Durumu (Weather)
- Çocuk Gelişimi (Child Development)
- Kişisel Sağlık (Personal Health)
- Aile Danışmanı (Family Advisor)

**Report Types:**
- Personal wellness
- Family updates
- Environmental information
- Lifestyle recommendations

---

## Expertise-Based Sections

Reports are also organized by the advisor's expertise area. This allows users to follow a specific advisor or explore all work from a particular specialist.

### Primary Advisors (12 Total)

1. **📊 Veri Analisti** (Data Analyst)
   - Business intelligence and metrics
   - Performance analysis

2. **👔 Operasyon Müdürü** (Operations Director)
   - Daily operations management
   - Process optimization

3. **📧 E-Posta Analisti** (Email Analyst)
   - Email pattern analysis
   - Communication management

4. **📋 İş Analisti** (Work Analyst)
   - Task tracking and accountability
   - Project status updates

5. **🌐 Sektör & Rekabet** (Sector Intelligence)
   - Industry trends
   - Competitive analysis

6. **🎯 Müşteri Deneyimi** (Customer Experience)
   - Customer insights
   - Experience optimization

7. **💡 Yapay Zeka İnovasyon** (AI Innovation)
   - Technology innovations
   - AI applications

8. **🎓 Kariyer & İK** (Career & HR)
   - Career development
   - HR analytics

9. **🎤 İletişim** (Communications)
   - Communication strategies
   - Collaboration patterns

10. **📚 Öğrenme** (Learning Resources)
    - Educational content
    - Skill development

11. **🏋️ Kişisel Gelişim** (Personal Development)
    - Personal improvement
    - Coaching insights

12. **🌡️ Operasyon Sabahçı** (Morning Operations)
    - Daily briefing
    - Operational readiness

---

## Filtering & Navigation

### Date Range Filtering
Users can filter reports by:
- Today's reports
- Last 7 days
- Last 30 days
- Custom date range
- Specific date selection

### Priority Filtering
Reports can be filtered by priority level:
- Critical/High priority
- Medium priority
- Low priority
- All priorities (default)

### Status Filtering
Filter by report status:
- Completed/Published
- Pending (drafts)
- All (default)

### Search Functionality
- Full-text search across report titles and content
- Filter by advisor name
- Filter by category/topic
- Search results highlighting

---

## Features

### Document Archive (30-Day Rolling Window)
- Automatic archival of reports older than 30 days
- Historical reference access
- Archive statistics

### Export & Print Options
- Export individual reports as PDF
- Print directly from browser
- Export as Markdown
- Export date range as ZIP

### Responsive Design
- Mobile-optimized layout
- Tablet-friendly views
- Desktop full-featured view
- Touch-friendly controls
- Auto-adjusting font sizes

### Performance
- Lazy loading of report content
- Efficient filtering and search
- Client-side caching
- Optimized rendering

---

## User Experience Flow

### Primary Navigation
1. **List View** — Default view showing today's or latest reports in organized grid
2. **Topic View** — Browse by business domain
3. **Expertise View** — Browse by advisor specialty
4. **Archive View** — Historical reports (30 days)
5. **Search View** — Full-text search results

### Interaction Patterns

#### Browsing Reports
```
Dashboard (Sistem Tab)
↓
Content Tab (İçerik & Raporlar)
↓
Select View (List/Topic/Expertise)
↓
Apply Filters (Date/Priority/Status)
↓
Click Report Card
↓
Read Full Document
↓
Export/Print/Share
```

#### Finding Specific Reports
```
Search by keyword
↓
Filter by date range
↓
Filter by advisor
↓
View results
↓
Select and read
```

---

## Technical Implementation

### Data Flow
1. **Status API** provides current reports list
2. **Archive API** provides historical report index
3. **Report API** provides individual report content
4. **Indexing** organizes reports into topic/expertise categories
5. **Frontend** renders with interactive filtering

### Caching
- Archive index: 1 hour
- Individual reports: Session
- Search results: Session
- Filter state: Session

### Accessibility
- Semantic HTML structure
- ARIA labels for interactive elements
- Keyboard navigation support
- Screen reader compatibility
- High contrast support

---

## Performance Metrics

### Load Times
- List view: < 500ms
- Topic view: < 1s
- Archive view: < 2s
- Full search: < 1.5s

### Optimization
- Report cards lazy-load content
- Archive uses pagination
- Search uses debouncing
- Filter state managed efficiently

---

## Future Enhancements

- Collaborative annotations on reports
- Report versioning and comparison
- Scheduled report delivery
- Custom report templates
- Report rating and feedback
- Advanced analytics on report usage
- AI-powered report summarization
- Custom dashboard layouts
