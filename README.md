# Jaderson Cim Advogados

Repositório do site do escritório Jaderson Cim Advogados.

## Monitoramento DJEN

Este repositório monitora automaticamente o **DJEN — Diário da Justiça Eletrônico Nacional** (CNJ) para as OABs do escritório:

- OAB/SC 33.863
- OAB/SP 411.766
- OAB/MG 198.189

### Como funciona

- O workflow `.github/workflows/djen-monitor.yml` roda **todo dia às 07:00 BRT** (e pode ser disparado manualmente em *Actions → Monitor DJEN → Run workflow*).
- O script `scripts/monitor_djen.py` consulta a API pública do CNJ (`comunicaapi.pje.jus.br`) para cada OAB nos últimos 7 dias.
- Novas publicações são gravadas em `publicacoes/AAAA-MM-DD.md` (legível) e `publicacoes/AAAA-MM-DD.json` (estruturado).
- IDs já vistos ficam em `state/seen_ids.json` para evitar duplicação entre execuções.

### Configuração

Edite `config/oabs.json` para ajustar OABs, janela de busca ou paginação:

```json
{
  "oabs": [
    { "uf": "SC", "numero": "33863" },
    { "uf": "SP", "numero": "411766" },
    { "uf": "MG", "numero": "198189" }
  ],
  "dias_retroativos": 7,
  "itens_por_pagina": 100
}
```

### Rodar localmente

```bash
python3 scripts/monitor_djen.py
```

Sem dependências externas — só Python 3.10+.
