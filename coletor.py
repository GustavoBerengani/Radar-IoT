import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import serial
from pydantic import BaseModel, Field, ValidationError
from typing import Literal


class Passagem(BaseModel):
    radar_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    evento_id: int = Field(ge=1, le=4294967295)
    distancia_sensores_m: float = Field(gt=0, le=100)
    tempo_ms: float = Field(gt=0, le=60000)
    velocidade_kmh: float = Field(gt=0, le=1000)
    velocidade_max_kmh: float = Field(gt=0, le=1000)
    sentido: Literal["ida", "volta"]
    status: Literal["normal", "excesso"]


def enviar(base, rota, dados):
    req = Request(base + rota, data=dados.encode(), method="POST", headers={
        "Content-Type": "application/json", "X-Radar-Key": os.getenv("RADAR_API_KEY", ""),
    })
    with urlopen(req, timeout=2) as resposta:
        resposta.read()


def enfileirar(fila, evento, simulado=False):
    payload = Passagem.model_validate(evento).model_dump()
    payload.update(captura_id=str(uuid4()), capturado_em=datetime.now(timezone.utc).isoformat(),
                   simulado=simulado)
    with fila:
        fila.execute("INSERT INTO fila (dados) VALUES (?)", (json.dumps(payload),))
    print(f"Capturado: {payload['velocidade_kmh']:.2f} km/h", flush=True)


def ler_serial(arduino, buffer):
    bloco = arduino.read(arduino.in_waiting or 1)
    linhas = (buffer + bloco).split(b"\n")
    for linha in linhas[:-1]:
        linha = linha.strip()
        if not linha or linha.startswith(b"#"):
            continue
        yield linha, b""
    sobra = linhas[-1]
    yield None, sobra if len(sobra) <= 4096 else b""


def executar(args):
    porta = None
    buffer = b""
    tentar_em = proximo_status = proximo_envio = proxima_simulacao = 0.0
    evento_simulado = 0
    with sqlite3.connect(args.fila) as fila:
        fila.execute("CREATE TABLE IF NOT EXISTS fila (id INTEGER PRIMARY KEY, dados TEXT NOT NULL)")
        fila.execute("CREATE TABLE IF NOT EXISTS rejeitados (dados TEXT NOT NULL, erro TEXT NOT NULL)")
        try:
            while True:
                agora = time.monotonic()
                if args.simular:
                    if agora >= proxima_simulacao:
                        evento_simulado += 1
                        tempo = [525.02, 100, 350, 200][(evento_simulado - 1) % 4]
                        velocidade = round(0.15 * 3600 / tempo, 2)
                        enfileirar(fila, dict(radar_id="SIMULADOR", evento_id=evento_simulado,
                            distancia_sensores_m=0.15, tempo_ms=tempo, velocidade_kmh=velocidade,
                            velocidade_max_kmh=4, sentido="ida",
                            status="excesso" if velocidade > 4 else "normal"), True)
                        proxima_simulacao = agora + 3
                    time.sleep(0.15)
                else:
                    if porta is None and agora >= tentar_em:
                        try:
                            porta = serial.Serial(args.porta, args.baud, timeout=0.15)
                            buffer = b""
                            proximo_status = 0
                            print(f"Serial aberta: {args.porta} a {args.baud}", flush=True)
                        except (serial.SerialException, OSError) as erro:
                            print(f"Serial indisponível: {erro}. Nova tentativa em 3 s.", flush=True)
                            tentar_em = agora + 3
                    if porta is not None:
                        try:
                            for linha, buffer in ler_serial(porta, buffer):
                                if linha is not None:
                                    try:
                                        enfileirar(fila, json.loads(linha))
                                    except (ValueError, ValidationError) as erro:
                                        print(f"Linha descartada: {erro}", flush=True)
                        except (serial.SerialException, OSError) as erro:
                            print(f"Serial desconectada: {erro}", flush=True)
                            porta.close()
                            porta = None
                            tentar_em = agora + 3
                            proximo_status = 0
                    else:
                        time.sleep(0.15)

                if not args.simular and agora >= proximo_status:
                    proximo_status = agora + 5
                    try:
                        enviar(args.api, "/api/status", json.dumps(
                            dict(conectado=porta is not None, porta=args.porta)))
                    except (URLError, OSError) as erro:
                        print(f"Status pendente: {erro}", flush=True)

                if agora >= proximo_envio:
                    for id_fila, dados in fila.execute("SELECT id, dados FROM fila ORDER BY id LIMIT 20").fetchall():
                        try:
                            enviar(args.api, "/api/registros", dados)
                            print("Enviado ao dashboard.", flush=True)
                        except HTTPError as erro:
                            if erro.code not in (400, 422):
                                print(f"Envio pendente: HTTP {erro.code}", flush=True)
                                proximo_envio = agora + 3
                                break
                            motivo = erro.read(4096).decode(errors="replace")
                            with fila:
                                fila.execute("INSERT INTO rejeitados VALUES (?, ?)", (dados, motivo))
                                fila.execute("DELETE FROM fila WHERE id=?", (id_fila,))
                            print(f"API rejeitou a passagem: {motivo}", flush=True)
                            continue
                        except (URLError, OSError) as erro:
                            print(f"Envio pendente: {erro}", flush=True)
                            proximo_envio = agora + 3
                            break
                        with fila:
                            fila.execute("DELETE FROM fila WHERE id=?", (id_fila,))
        except KeyboardInterrupt:
            print("\nColeta encerrada.", flush=True)
        finally:
            if porta is not None:
                porta.close()
            if not args.simular:
                try:
                    enviar(args.api, "/api/status", json.dumps(dict(conectado=False, porta=args.porta)))
                except (URLError, OSError):
                    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--porta", default="COM3")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--api", default="http://127.0.0.1:8000", type=lambda url: url.rstrip("/"))
    parser.add_argument("--fila", default=str(Path(__file__).with_name("fila.sqlite3")))
    parser.add_argument("--simular", action="store_true")
    executar(parser.parse_args())
