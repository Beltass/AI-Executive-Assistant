"""Slack üzerinden rapor SİPARİŞ etme katmanı — menü menü, adım adım.

Bu paket kullanıcının Slack'te yazarak rapor istemesini sağlar. Analiz motorunu
(:mod:`ai_assistant.analysis`) yalnızca ÇAĞIRIR; hesap yapmaz, biçim üretmez.

MİMARİ KISITI — NEDEN DÜĞME YOK
--------------------------------

Bu proje GitHub Actions cron üzerinde çalışır; açık bir HTTPS ucu YOKTUR. Slack
düğmeleri ve Events API bir sunucuya ``POST`` eder, yani bu kurulumda
kullanılamazlar. Bunun yerine YOKLAMA (polling) vardır:

1. zamanlanmış iş :mod:`ai_assistant.chat.poller` ile kanalı okur
   (``conversations.history``, kalıcı bir imleçten sonrası),
2. mesajı :mod:`ai_assistant.chat.session` durum makinesine verir,
3. yanıtı ``chat.postMessage`` ile geri yazar.

Menüler NUMARALI METİNDİR ("1, 2, 3 — numarayı yaz"), düğme değil.

DÜĞMEYE GEÇİŞ HAZIR
-------------------

Durum makinesi metin değil :class:`ai_assistant.chat.menu.Prompt` üretir: bir
başlık ve seçenek listesi. Metne çevirme işi
:class:`~ai_assistant.chat.menu.TextRenderer` içindedir; Block Kit düğmeleri
üreten :class:`~ai_assistant.chat.menu.BlockRenderer` de aynı arayüzü uygular.
Bir gün bir sunucu geldiğinde değişecek tek şey seçilen renderer ve seçimin
nereden geldiğidir (``action_id`` vs. yazılan numara) — akış değil.

HER SÜRECİ AYRI DÜŞÜN
---------------------

Her cron yoklaması YENİ BİR SÜREÇTİR. Bellekte durum tutmak yoktur: imleç,
oturumlar ve şablonlar :mod:`ai_assistant.chat.store` üzerinden diske yazılır ve
her yoklamada yeniden okunur.

TEK KURAL: kullanıcı hiçbir zaman sessiz bırakılmaz. Tanınmayan girdi, okunamayan
dosya, eksik kimlik — hepsi kanala Türkçe bir cümle olarak döner.
"""

from __future__ import annotations

from .spec import ReportSpec

__all__ = ["ReportSpec"]
