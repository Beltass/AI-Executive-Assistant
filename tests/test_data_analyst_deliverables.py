"""Veri Analisti'nin ÇIKTILARI: Excel, sunum taslağı, Drive teslimi.

Bu dosya brifingin metnini değil, danışmanın ürettiği DOSYALARI sınar. Ayrım
önemli: "rapor yazdım" demek kolay, gerçekten açılabilen bir ``.xlsx`` üretmek
zordur — burada dosyanın var olduğu, boyutunun sıfır olmadığı ve openpyxl ile
GERÇEKTEN açıldığı doğrulanır.

Sunum tarafında sınır bilinçlidir: Google Slides API'si bu projede yok, o
yüzden slayt DOSYASI değil, yapılandırılmış bir taslak üretilir ve bu sınır
kullanıcıya yazılı olarak söylenir. Test bunu da bir iddia olarak tutar —
ileride biri "sunum oluşturuldu" yazmaya kalkarsa kırılsın.

Her şey ÇEVRİMDIŞI: model anahtarı yok, ağ yok, Google kimliği yok.
"""

from __future__ import annotations

import os

import pytest

from ai_assistant import config
from ai_assistant.advisors import data_analyst as analyst_module
from ai_assistant.advisors.data_analyst import DataAnalystAdvisor
from ai_assistant.integrations import STATUS_OK

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cagri_merkezi.csv")

_ENV_VARS = (
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "DATA_ANALYST_SOURCE",
    "DATA_ANALYST_DRIVE_FOLDER_ID",
    "DATA_ANALYST_OUTPUT_DIR",
    "DATA_ANALYST_OUTPUT_FOLDER_ID",
    "DATA_ANALYST_MAX_SLIDES",
    "DATA_ANALYST_EXCEL",
    "GOOGLE_DRIVE_FOLDER_ID",
)


@pytest.fixture()
def local_dataset(monkeypatch, tmp_path):
    """Sentetik çağrı merkezi CSV'si + izole bir çıktı klasörü."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "DEFAULT_SETTINGS", {})
    monkeypatch.setenv("DATA_ANALYST_SOURCE", FIXTURE)
    monkeypatch.setenv("DATA_ANALYST_OUTPUT_DIR", str(tmp_path / "cikti"))
    yield tmp_path / "cikti"


def _analysed():
    advisor = DataAnalystAdvisor()
    advisor._prepare()
    assert advisor._error is None
    return advisor


# --- Excel -------------------------------------------------------------------


def test_excel_workbook_is_a_real_file_that_openpyxl_can_open(local_dataset):
    """"Excel ürettim" iddiası dosyanın KENDİSİYLE doğrulanır."""
    openpyxl = pytest.importorskip("openpyxl")
    advisor = _analysed()

    path = analyst_module.write_workbook(advisor._result, str(local_dataset))

    assert os.path.isfile(path)
    assert path.endswith(".xlsx")
    assert os.path.getsize(path) > 5_000  # boş bir kabuk değil
    workbook = openpyxl.load_workbook(path)
    try:
        # Kapak + KPI + ham veri en azından burada olmalı.
        assert len(workbook.sheetnames) >= 3
        assert "Göstergeler" in workbook.sheetnames  # özet tablo
        assert "Kapak" in workbook.sheetnames
    finally:
        workbook.close()


def test_workbook_contains_a_summary_table_and_a_chart(local_dataset):
    """Özet tablo + grafik: kullanıcının istediği iki şey de kitapta."""
    openpyxl = pytest.importorskip("openpyxl")
    advisor = _analysed()
    path = analyst_module.write_workbook(advisor._result, str(local_dataset))

    workbook = openpyxl.load_workbook(path)
    try:
        charts = sum(len(getattr(ws, "_charts", [])) for ws in workbook.worksheets)
        assert charts >= 1, "kırılım sayfalarında en az bir grafik olmalı"
        # Özet (gösterge) sayfasında birden çok satır var.
        assert workbook["Göstergeler"].max_row > 2
    finally:
        workbook.close()


def test_excel_can_be_switched_off_without_losing_the_rest(local_dataset, monkeypatch):
    monkeypatch.setenv("DATA_ANALYST_EXCEL", "false")
    advisor = _analysed()

    produced = analyst_module.produce_deliverables(
        advisor._result, advisor._findings, advisor._limits, upload=False
    )

    assert produced.excel_path == ""
    assert produced.slides  # sunum taslağı yaşamaya devam eder
    assert any("Excel üretimi kapalı" in note for note in produced.notes)


# --- sunum taslağı -----------------------------------------------------------


def test_slide_outline_is_built_from_the_engine_not_the_model(local_dataset):
    advisor = _analysed()
    slides = analyst_module.build_slide_outline(
        advisor._result, advisor._findings, advisor._limits
    )

    assert 3 <= len(slides) <= analyst_module.DEFAULT_MAX_SLIDES
    titles = [slide["title"] for slide in slides]
    assert "Karar özeti" in titles
    assert "Aksiyonlar" in titles
    # Her slaytın maddesi var; boş slayt üretilmez.
    assert all(slide["bullets"] for slide in slides)
    # Sayılar motordan geliyor: SLA değeri taslakta aynen görünür.
    flat = "\n".join(b for slide in slides for b in slide["bullets"])
    assert "%84,2" in flat


def test_slide_outline_states_that_no_slides_file_was_created(local_dataset):
    """Yapamadığımız şeyi yapmış gibi göstermiyoruz."""
    advisor = _analysed()
    slides = analyst_module.build_slide_outline(
        advisor._result, advisor._findings, advisor._limits
    )
    rendered = analyst_module.render_slide_outline(slides)

    assert "Sunum DOSYASI oluşturulmadı" in rendered
    assert "Google Slides API istemcisi yok" in rendered
    assert "Slayt 1 —" in rendered


def test_slide_count_is_capped_by_configuration(local_dataset, monkeypatch):
    monkeypatch.setenv("DATA_ANALYST_MAX_SLIDES", "4")
    advisor = _analysed()
    slides = analyst_module.build_slide_outline(
        advisor._result, advisor._findings, advisor._limits
    )
    assert len(slides) == 4


# --- brifingle birleşim ------------------------------------------------------


def test_briefing_carries_the_outline_and_names_the_produced_files(local_dataset):
    briefing = DataAnalystAdvisor().generate_briefing()

    assert briefing.status == STATUS_OK
    assert analyst_module.SLIDE_HEADING in briefing.text
    assert analyst_module.DELIVERABLES_HEADING in briefing.text
    assert ".xlsx" in briefing.text

    written = sorted(p.name for p in local_dataset.iterdir())
    assert any(name.endswith(".xlsx") for name in written)
    assert any(name.endswith("-sunum.md") for name in written)


def test_produced_files_are_listed_as_report_sources(local_dataset):
    briefing = DataAnalystAdvisor().generate_briefing()
    sources = briefing.report["sources"]
    titles = [item["title"] for item in sources]
    assert any(title.endswith(".xlsx") for title in titles)
    assert any(title.endswith("-sunum.md") for title in titles)


# --- Drive teslimi -----------------------------------------------------------


class _FakeDrive:
    """Sahte Drive istemcisi: ne yüklendiğini kaydeder, ağa çıkmaz."""

    def __init__(self):
        self.uploads = []

    def upload_report(self, name, content, folder_id, mime_type=""):
        self.uploads.append((name, content, folder_id, mime_type))
        return f"id-{len(self.uploads)}"

    def get_file_link(self, file_id):
        return f"https://drive.example/{file_id}"


def test_upload_sends_the_workbook_as_bytes_and_returns_links(
    local_dataset, monkeypatch
):
    advisor = _analysed()
    produced = analyst_module.produce_deliverables(
        advisor._result, advisor._findings, advisor._limits, upload=False
    )
    drive = _FakeDrive()

    analyst_module.upload_deliverables(produced, folder_id="KLASOR", client=drive)

    names = [item[0] for item in drive.uploads]
    assert any(name.endswith(".xlsx") for name in names)
    assert any(name.endswith("-sunum.md") for name in names)
    # Excel METİN değil BAYT olarak gider — yoksa dosya bozulur.
    payloads = {item[0]: item[1] for item in drive.uploads}
    excel_name = next(name for name in names if name.endswith(".xlsx"))
    assert isinstance(payloads[excel_name], bytes)
    assert payloads[excel_name][:2] == b"PK"  # zip başlığı: gerçek bir xlsx
    assert produced.excel_link.startswith("https://drive.example/")


def test_upload_is_explicit_when_no_drive_folder_is_configured(local_dataset):
    advisor = _analysed()
    produced = analyst_module.produce_deliverables(
        advisor._result, advisor._findings, advisor._limits, upload=False
    )

    analyst_module.upload_deliverables(produced, folder_id="")

    assert produced.excel_link == ""
    assert any("Drive'a yüklenmedi" in note for note in produced.notes)
    # Yerel dosya yine duruyor: yükleyememek üretememek değildir.
    assert os.path.isfile(produced.excel_path)
