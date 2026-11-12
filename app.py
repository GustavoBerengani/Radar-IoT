import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DB = Path(os.getenv("RADAR_DB", str(ROOT / "radar.sqlite3")))
WRITE_KEY = os.getenv("RADAR_API_KEY", "")
ADMIN_KEY = os.getenv("RADAR_ADMIN_KEY", WRITE_KEY)


class Evento(BaseModel):
    captura_id: UUID
    radar_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    evento_id: int = Field(ge=1, le=4294967295)
    distancia_sensores_m: float = Field(gt=0, le=100)
    tempo_ms: float = Field(gt=0, le=60000)
    velocidade_kmh: float = Field(gt=0, le=1000)
    velocidade_max_kmh: float = Field(gt=0, le=1000)
    sentido: Literal["ida", "volta"]
    status: Literal["normal", "excesso"]
    capturado_em: datetime
    simulado: bool = False


class Associacao(BaseModel):
    participante: str = Field(max_length=80)


class EstadoColeta(BaseModel):
    conectado: bool
    porta: str = Field(max_length=32)


@contextmanager
def banco():
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


DB.parent.mkdir(parents=True, exist_ok=True)
with banco() as conn:
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY,
            captura_id TEXT UNIQUE NOT NULL,
            radar_id TEXT NOT NULL,
            evento_id INTEGER NOT NULL,
            distancia_sensores_m REAL NOT NULL,
            tempo_ms REAL NOT NULL,
            velocidade_kmh REAL NOT NULL,
            velocidade_max_kmh REAL NOT NULL,
            sentido TEXT NOT NULL,
            status TEXT NOT NULL,
            capturado_em TEXT NOT NULL,
            simulado INTEGER NOT NULL,
            participante TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS registros_fonte_data
            ON registros (simulado, capturado_em);
        CREATE TABLE IF NOT EXISTS coleta (
            id INTEGER PRIMARY KEY CHECK(id=1),
            conectado INTEGER NOT NULL,
            porta TEXT NOT NULL,
            atualizado REAL NOT NULL
        );
    """)

app = FastAPI(title="Radar IoT", version="1.0")
pages_origin = os.getenv("RADAR_PAGES_ORIGIN", "").strip().rstrip("/")
if pages_origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[pages_origin],
        allow_methods=["GET", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Radar-Key"],
    )


@app.get("/config.js", include_in_schema=False)
def configuracao_web():
    return FileResponse(ROOT / "web" / "config.js", media_type="application/javascript")



def autorizar(esperada, recebida):
    if esperada and not secrets.compare_digest(esperada.encode(), recebida.encode()):
        raise HTTPException(401, "Chave da API inválida")


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(ROOT / "web" / "index.html")


@app.post("/api/registros")
def registrar(evento: Evento, x_radar_key: str = Header(default="")):
    autorizar(WRITE_KEY, x_radar_key)
    if evento.capturado_em.utcoffset() is None:
        raise HTTPException(422, "Data deve incluir fuso horário")
    calculada = evento.distancia_sensores_m * 3600 / evento.tempo_ms
    if abs(calculada - evento.velocidade_kmh) > max(0.02, calculada * 0.01):
        raise HTTPException(422, "Velocidade incompatível com distância e tempo")
    dados = evento.model_dump(mode="json")
    dados["capturado_em"] = evento.capturado_em.astimezone(timezone.utc).isoformat()
    with banco() as conn:
        conn.execute("""
            INSERT INTO registros (captura_id, radar_id, evento_id, distancia_sensores_m,
                tempo_ms, velocidade_kmh, velocidade_max_kmh, sentido, status, capturado_em, simulado)
            VALUES (:captura_id, :radar_id, :evento_id, :distancia_sensores_m,
                :tempo_ms, :velocidade_kmh, :velocidade_max_kmh, :sentido, :status, :capturado_em, :simulado)
            ON CONFLICT(captura_id) DO NOTHING
        """, dados)
        return dict(conn.execute("SELECT * FROM registros WHERE captura_id=?", (dados["captura_id"],)).fetchone())


@app.post("/api/status")
def atualizar_status(estado: EstadoColeta, x_radar_key: str = Header(default="")):
    autorizar(WRITE_KEY, x_radar_key)
    with banco() as conn:
        conn.execute("""
            INSERT INTO coleta VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET conectado=excluded.conectado,
                porta=excluded.porta, atualizado=excluded.atualizado
        """, (estado.conectado, estado.porta, time.time()))
    return {"ok": True}


@app.get("/api/status")
def status():
    with banco() as conn:
        estado = conn.execute("SELECT * FROM coleta WHERE id=1").fetchone()
    ativo = bool(estado and time.time() - estado["atualizado"] <= 16)
    return {"coletor": ativo, "arduino": bool(ativo and estado["conectado"]),
            "porta": estado["porta"] if ativo else None, "chave_edicao": bool(ADMIN_KEY), "exclusao": True}


@app.get("/api/registros")
def listar(simulado: bool = False, radar: str = "", participante: str = "",
           situacao: Literal["", "normal", "excesso"] = "",
           inicio: datetime | None = None, fim: datetime | None = None,
           minima: float | None = Query(None, ge=0), maxima: float | None = Query(None, ge=0),
           pagina: int = Query(1, ge=1, le=100000), limite: int = Query(25, ge=1, le=100)):
    condicoes = ["simulado = ?"]
    parametros = [simulado]
    for filtro, coluna, operador in [
        (radar, "radar_id", "="), (participante, "participante", "LIKE"),
        (situacao, "status", "="), (inicio, "capturado_em", ">="),
        (fim, "capturado_em", "<="), (minima, "velocidade_kmh", ">="),
        (maxima, "velocidade_kmh", "<="),
    ]:
        if filtro is None or filtro == "":
            continue
        if isinstance(filtro, datetime):
            if filtro.utcoffset() is None:
                raise HTTPException(422, "Filtro de data deve incluir fuso")
            filtro = filtro.astimezone(timezone.utc).isoformat()
        if operador == "LIKE":
            filtro = f"%{filtro}%"
        condicoes.append(f"{coluna} {operador} ?")
        parametros.append(filtro)
    where = " AND ".join(condicoes)
    with banco() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM registros WHERE {where}", parametros).fetchone()[0]
        linhas = conn.execute(f"""
            SELECT * FROM registros WHERE {where}
            ORDER BY capturado_em DESC, id DESC LIMIT ? OFFSET ?
        """, (*parametros, limite, (pagina - 1) * limite))
        return {"total": total, "registros": [dict(linha) for linha in linhas]}


@app.get("/api/estatisticas")
def estatisticas(simulado: bool = False):
    with banco() as conn:
        stats = conn.execute("""
            SELECT COUNT(*) AS total, AVG(velocidade_kmh) AS media,
                   MAX(velocidade_kmh) AS maior,
                   COUNT(CASE WHEN status='excesso' THEN 1 END) AS excessos
            FROM registros WHERE simulado=?
        """, (simulado,)).fetchone()
        recentes = conn.execute("""
            SELECT capturado_em, velocidade_kmh, velocidade_max_kmh, status
            FROM registros WHERE simulado=? ORDER BY capturado_em DESC, id DESC LIMIT 30
        """, (simulado,)).fetchall()
    return {**dict(stats), "recentes": [dict(linha) for linha in reversed(recentes)]}


@app.get("/api/ranking")
def ranking(simulado: bool = False, ordem: Literal["maior", "media", "passagens"] = "maior"):
    with banco() as conn:
        return [dict(linha) for linha in conn.execute(f"""
            SELECT participante, MAX(velocidade_kmh) AS maior,
                AVG(velocidade_kmh) AS media, COUNT(*) AS passagens,
                COUNT(CASE WHEN status='excesso' THEN 1 END) AS excessos
            FROM registros WHERE simulado=? AND participante <> ''
            GROUP BY participante ORDER BY {ordem} DESC, participante
        """, (simulado,))]


@app.patch("/api/registros/{registro_id}/participante")
def associar(registro_id: int, associacao: Associacao, x_radar_key: str = Header(default="")):
    autorizar(ADMIN_KEY, x_radar_key)
    with banco() as conn:
        cursor = conn.execute("UPDATE registros SET participante=? WHERE id=?",
                              (associacao.participante.strip(), registro_id))
        if not cursor.rowcount:
            raise HTTPException(404, "Registro não encontrado")
    return {"ok": True}

@app.delete("/api/registros/{captura_id}")
def excluir_registro(captura_id: UUID):
    with banco() as conn:
        cursor = conn.execute("DELETE FROM registros WHERE captura_id=? AND simulado=0",
                              (str(captura_id),))
        if cursor.rowcount == 0:
            raise HTTPException(404, "Registro não encontrado")
    return {"excluidos": 1}


@app.delete("/api/registros")
def limpar_registros(confirmacao: Literal["LIMPAR"]):
    with banco() as conn:
        cursor = conn.execute("DELETE FROM registros WHERE simulado=0")
        return {"excluidos": cursor.rowcount}
