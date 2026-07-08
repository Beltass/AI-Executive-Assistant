# integrations/

Servis bazlı connector kodu (OAuth akışı + API istemcisi), her
servis kendi alt klasöründe, ör.:

```
integrations/
├── gmail/
├── google-calendar/
├── outlook/        # Faz 2
├── teams/           # Faz 3
├── slack/            # Faz 3
├── notion/             # Faz 3
└── linkedin/            # Faz 3
```

Detaylar `../docs/INTEGRATIONS.md` içinde yazılacak (Faz 2). Faz 1'de
yalnızca `gmail/` ve `google-calendar/` doldurulur.
