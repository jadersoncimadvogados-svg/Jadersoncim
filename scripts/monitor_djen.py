#!/usr/bin/env python3
"""Monitora o DJEN (Diário da Justiça Eletrônico Nacional) para OABs configuradas.

Consulta a API pública do CNJ (https://comunicaapi.pje.jus.br) e gera um
relatório em Markdown + JSON com as novas publicações encontradas, mantendo
um estado local de IDs já vistos para evitar duplicação entre execuções.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "oabs.json"
STATE_PATH = ROOT / "state" / "seen_ids.json"
OUTPUT_DIR = ROOT / "publicacoes"

API_URL = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
USER_AGENT = "djen-monitor/1.0 (+https://github.com/jadersoncimadvogados-svg/jadersoncim)"


@dataclass
class OAB:
    uf: str
    numero: str

    def label(self) -> str:
        return f"OAB/{self.uf} {self.numero}"


def load_config() -> tuple[list[OAB], int, int]:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    oabs = [OAB(uf=o["uf"].upper(), numero=str(o["numero"])) for o in data["oabs"]]
    dias = int(data.get("dias_retroativos", 7))
    itens = int(data.get("itens_por_pagina", 100))
    return oabs, dias, itens


def load_state() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    try:
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return set()


def save_state(seen: set[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_page(params: dict[str, Any], attempt: int = 1) -> dict[str, Any]:
    url = f"{API_URL}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        if attempt >= 4:
            raise RuntimeError(f"falha ao consultar DJEN: {exc}") from exc
        time.sleep(2 ** attempt)
        return fetch_page(params, attempt + 1)


def fetch_publicacoes(oab: OAB, inicio: date, fim: date, itens_por_pagina: int) -> list[dict[str, Any]]:
    pagina = 1
    todos: list[dict[str, Any]] = []
    while True:
        params = {
            "numeroOab": oab.numero,
            "ufOab": oab.uf,
            "dataDisponibilizacaoInicio": inicio.isoformat(),
            "dataDisponibilizacaoFim": fim.isoformat(),
            "itensPorPagina": itens_por_pagina,
            "pagina": pagina,
        }
        payload = fetch_page(params)
        items = payload.get("items") or []
        todos.extend(items)
        if len(items) < itens_por_pagina:
            break
        pagina += 1
        if pagina > 50:
            break
    return todos


def normalize_id(item: dict[str, Any]) -> str:
    raw = item.get("id") or item.get("hash") or item.get("numeroComunicacao")
    if raw is None:
        # fallback: combinação que tende a ser única
        raw = "|".join(
            str(item.get(k, "")) for k in ("numero_processo", "data_disponibilizacao", "siglaTribunal", "texto")
        )
    return str(raw)


def render_markdown(data_execucao: date, novos_por_oab: dict[str, list[dict[str, Any]]]) -> str:
    total = sum(len(v) for v in novos_por_oab.values())
    linhas: list[str] = []
    linhas.append(f"# Publicações DJEN — {data_execucao.isoformat()}")
    linhas.append("")
    linhas.append(f"Total de novas publicações: **{total}**")
    linhas.append("")

    for oab_label, itens in novos_por_oab.items():
        linhas.append(f"## {oab_label} — {len(itens)} publicação(ões)")
        linhas.append("")
        if not itens:
            linhas.append("_Sem novas publicações no período._")
            linhas.append("")
            continue
        for it in itens:
            tribunal = it.get("siglaTribunal") or "—"
            orgao = it.get("nomeOrgao") or "—"
            processo = it.get("numero_processo") or it.get("numeroprocessocommascara") or "—"
            data_disp = it.get("data_disponibilizacao") or "—"
            tipo = it.get("tipoComunicacao") or "—"
            classe = it.get("nomeClasse") or "—"
            link = it.get("link") or ""
            texto = (it.get("texto") or "").strip()
            if len(texto) > 1500:
                texto = texto[:1500].rstrip() + "…"

            linhas.append(f"### {tribunal} — Processo {processo}")
            linhas.append("")
            linhas.append(f"- **Órgão:** {orgao}")
            linhas.append(f"- **Classe:** {classe}")
            linhas.append(f"- **Tipo:** {tipo}")
            linhas.append(f"- **Disponibilizado em:** {data_disp}")
            if link:
                linhas.append(f"- **Link:** {link}")
            destinatarios = it.get("destinatarios") or []
            if destinatarios:
                nomes = ", ".join(d.get("nome", "") for d in destinatarios if d.get("nome"))
                if nomes:
                    linhas.append(f"- **Destinatário(s):** {nomes}")
            linhas.append("")
            if texto:
                linhas.append("```")
                linhas.append(texto)
                linhas.append("```")
                linhas.append("")
    return "\n".join(linhas)


def main() -> int:
    oabs, dias, itens_por_pagina = load_config()
    seen = load_state()

    hoje = date.today()
    inicio = hoje - timedelta(days=dias)

    novos_por_oab: dict[str, list[dict[str, Any]]] = {}
    todos_itens: list[dict[str, Any]] = []
    novos_ids: set[str] = set()

    for oab in oabs:
        print(f"[djen] consultando {oab.label()} de {inicio} a {hoje}…", file=sys.stderr)
        try:
            itens = fetch_publicacoes(oab, inicio, hoje, itens_por_pagina)
        except RuntimeError as exc:
            print(f"[djen] erro em {oab.label()}: {exc}", file=sys.stderr)
            novos_por_oab[oab.label()] = []
            continue

        novos: list[dict[str, Any]] = []
        for it in itens:
            uid = f"{oab.uf}-{oab.numero}-{normalize_id(it)}"
            if uid in seen:
                continue
            novos.append(it)
            novos_ids.add(uid)
            todos_itens.append({"oab": oab.label(), **it})

        novos_por_oab[oab.label()] = novos
        print(f"[djen] {oab.label()}: {len(itens)} no período, {len(novos)} novas", file=sys.stderr)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUTPUT_DIR / f"{hoje.isoformat()}.md"
    json_path = OUTPUT_DIR / f"{hoje.isoformat()}.json"

    md_path.write_text(render_markdown(hoje, novos_por_oab), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "executado_em": datetime.utcnow().isoformat() + "Z",
                "periodo": {"inicio": inicio.isoformat(), "fim": hoje.isoformat()},
                "total_novas": sum(len(v) for v in novos_por_oab.values()),
                "publicacoes": todos_itens,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    seen.update(novos_ids)
    save_state(seen)

    total = sum(len(v) for v in novos_por_oab.values())
    print(f"[djen] concluído: {total} novas publicações gravadas em {md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
